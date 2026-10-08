"""The production wheel hook in xterm 5.5: cold/live modes and exact input."""
import json

import pytest

from test_codex_wheel import wheel_source
from test_snapshot_pane_modes_browser import CHROME, js  # noqa: F401

pytestmark = pytest.mark.skipif(CHROME is None, reason='no Chromium (set ORRERY_CHROME)')


@pytest.fixture
def wheel_page(js):
    js(wheel_source() + """
      var activeId='%1',packets=[],agent={program:'codex-cli',cmd:'node',provider:'openai',category:'agent',running:true};
      function currentAgentNamed(){return agent;}
      function send(packet){packets.push(packet);}
      async function probe(writes,meta={}){
        window.x=await apply(40,8,writes);
        const p={meta:{paneId:'%1',currentCommand:'codex',alternateOn:true,mouseTracking:false,...meta},
          session:'probe',term:x.t};
        setCodexWheelModes(p,p.meta);installCodexWheel(p);return p;
      }
      function inputs(){return {packets,data:x.data,binary:x.binary};}
    """)
    return js


@pytest.mark.parametrize('alternate', [False, True])
def test_cold_and_live_viewers_page_without_xterm_arrows(wheel_page, alternate):
    writes = ['\x1b[?1049h' if alternate else '', 'last lines']
    result = wheel_page(f"""(async()=>{{await probe({json.dumps(writes)});
      await wheelAt(x,5);return inputs();}})()""")
    assert result == {'packets': [{'type': 'codex-page', 'paneId': '%1', 'direction': 'up', 'count': 1}],
                      'data': [], 'binary': []}


@pytest.mark.parametrize('program', ['codex', 'claude'])
def test_mouse_on_keeps_the_existing_sgr_wheel_path(wheel_page, program):
    result = wheel_page(f"""(async()=>{{
      agent.program={json.dumps(program)}==='codex'?'codex-cli':'claude-code';agent.cmd={json.dumps(program)};agent.provider=agent.cmd==='codex'?'openai':'anthropic';
      await probe(['\\x1b[?1049h\\x1b[?1003h\\x1b[?1006hTEXT'],
        {{currentCommand:agent.cmd,mouseTracking:true}});
      await wheelAt(x,5);return inputs();}})()""")
    assert result['packets'] == [] and result['binary'] == []
    assert result['data'] == ['\x1b[<64;5;1M']


@pytest.mark.parametrize('kind', ['unknown', 'inactive', 'claude', 'shell'])
def test_unverified_panes_keep_xterm_alternate_scroll(wheel_page, kind):
    result = wheel_page(f"""(async()=>{{
      const kind={json.dumps(kind)};
      if(kind==='unknown')agent=null;
      if(kind==='inactive')activeId='%2';
      if(kind==='claude')agent.program='claude-code';
      await probe(['\\x1b[?1049hTEXT'],kind==='shell'?{{currentCommand:'sh'}}:{{}});
      await wheelAt(x,5);return inputs();}})()""")
    assert result['packets'] == [] and result['binary'] == []
    assert result['data'] and set(''.join(result['data']).split('\x1b[A')) == {''}


def test_live_mode_transitions_disable_the_fallback(wheel_page):
    result = wheel_page("""(async()=>{
      await probe(['last lines']);
      await new Promise(r=>x.t.write('\x1b[?1049l',r));
      await wheelAt(x,5);const normal=packets.length;
      await new Promise(r=>x.t.write('\x1b[?1049h\x1b[?1003h\x1b[?1006h',r));
      await wheelAt(x,5);return {normal,...inputs()};})()""")
    assert result['normal'] == 0 and result['packets'] == []
    assert result['data'] == ['\x1b[<64;5;1M']
