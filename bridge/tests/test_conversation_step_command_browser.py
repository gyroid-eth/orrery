"""On-demand command rendering in the actual desktop Reader."""
import json

import pytest

from test_conversation_review_regressions import cockpit
from test_conversation_step_command import claude_records, codex_record, projection
from test_conversation_steps_browser import prepare


def prepare_command(cockpit, tmp_path, provider, records, *args, **kwargs):
    row, store, events = projection(tmp_path, provider, records)
    payloads = {step['detail_ref']: store.read_step_command(step['detail_ref'], row)
                for event in events if (step := event.get('step')) and 'detail_ref' in step}
    js, wait, client = prepare(cockpit, provider, rows=events, working=False, *args, **kwargs)
    js('window.commandPayloads='+json.dumps(payloads)+''';
        window.commandReads=[];
        const source=OrreryConversationSource.Source;
        const original=source.prototype.stepCommand;
        const fixture=new source(async(url,options)=>{
          const urlObject=new URL(url,location.origin);
          commandReads.push({path:urlObject.pathname,ref:urlObject.searchParams.get('ref'),signal:options.signal});
          return {ok:true,json:async()=>commandPayloads[urlObject.searchParams.get('ref')]};
        });
        source.prototype.stepCommand=function(ref,options){return original.call(fixture,ref,options);};
        document.querySelector('.conversation-steps-toggle').click();
        window.commandToggle=document.querySelector('.conversation-step-diff-toggle:not([hidden])');
    ''')
    return js, wait, client


@pytest.mark.parametrize('provider', ['claude', 'codex'])
def test_command_is_fetched_on_click_and_renders_plain_text(cockpit, tmp_path, provider):
    cmd = 'pytest -k "<img id=fixture-command>"'
    output = '\x1b[31m<img id=fixture-output>\x1b[0m\n' + '\n'.join(f'output {i}' for i in range(1, 12))
    records = (claude_records('Exit code 7\n\n'+output, 'native error', error=True, cmd=cmd)
               if provider=='claude' else [codex_record(7, output, cmd)])
    js, wait, _ = prepare_command(cockpit, tmp_path, provider, records, theme='light')
    assert js("document.querySelector('.conversation-step-outcome').textContent") == 'exit 7'
    assert js("document.querySelector('.conversation-step-target').textContent") == 'pytest'
    assert js('commandReads.length') == 0
    assert js("!document.querySelector('.conversation-step-command')")
    js('commandToggle.click()')
    wait("document.querySelector('.conversation-step-output')!==null")
    assert js('commandReads.map(read=>read.path)') == ['/telemetry/conversation/detail']
    assert js("document.querySelector('.conversation-step-command').textContent") == '$ '+cmd
    assert js("document.querySelector('.conversation-step-output').textContent.split('\\n').length") == 8
    assert js("document.querySelector('.conversation-step-output').textContent.startsWith('<img id=fixture-output>')")
    assert js("!document.getElementById('fixture-output')&&!document.getElementById('fixture-command')")
    assert js("document.querySelector('.conversation-step-diff-fold').textContent") == 'Show 4 more lines'
    js("document.querySelector('.conversation-step-diff-fold').click()")
    assert js("document.querySelector('.conversation-step-output').textContent.split('\\n').length") == 12
    js("document.querySelector('.conversation-step-diff-fold').focus();commandToggle.click()")
    assert js("document.activeElement===commandToggle&&commandToggle.getAttribute('aria-expanded')==='false'")


def test_command_without_output(cockpit, tmp_path):
    js, wait, _ = prepare_command(cockpit, tmp_path, 'codex', [codex_record(0, '', 'true')])
    assert js("document.querySelector('.conversation-step-outcome').textContent") == ''
    js('commandToggle.click()')
    wait("document.querySelector('.conversation-step-diff-note')?.textContent==='No output'")


@pytest.mark.parametrize('cockpit', ['reply-demo'], indirect=True)
def test_demo_masks_command_and_output_before_showing_them(cockpit, tmp_path):
    cmd = "pytest /home/fixture-user/project/test_case.py"
    output = '\n'.join(['fixture-host https://fixture-host.test/tool'] + ['Fixture Person'] * 10)
    js, wait, _ = prepare_command(cockpit, tmp_path, 'codex', [codex_record(0, output, cmd)])
    assert js('OrreryDemo.on')
    js('commandToggle.click()')
    wait("document.querySelector('.conversation-step-output')!==null")
    assert js("document.querySelector('.conversation-step-command').textContent").startswith('$ pytest ')
    assert 'test_case.py' not in js("document.querySelector('.conversation-step-command').textContent")
    assert 'fixture-host' not in js("document.querySelector('.conversation-step-output').textContent")
    js("document.querySelector('.conversation-step-diff-fold').click()")
    assert 'Fixture Person' not in js("document.querySelector('.conversation-step-output').textContent")
