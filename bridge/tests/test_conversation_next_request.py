"""When does a History reader ask next? One function decides (conversation_view.js plan()).

Every row sets a state and measures when the next read starts. The rules:
- a user operation in flight (this tab or another): no held poll; when the
  last one ends, at once;
- the server can hold, did not refuse, the page has room: at once (after
  new rows, after CONTENT_GAP_MS);
- a catch-up page from a slot: at once;
- otherwise (no hold support, refused, a catch-up without a slot, a
  failure): the plain interval.
Includes RockyGuericke's slow POST and WintryLovelace's Load earlier → Latest (r5).
"""
import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'bridge/tests'))
from test_conversation_submissions import cockpit, prepare  # noqa: F401,E402

HARNESS = """window.R={reads:[],aborted:0,answer:()=>({hold:true})};
  OrreryConversationSource.Source.prototype.read=function(name,options){
    const r={at:performance.now(),after:options.after??null,before:options.before??null,wait:options.wait??0};R.reads.push(r);
    const a=R.answer(options,r,R.reads.length);
    if(a==='hold')return new Promise((_,reject)=>options.signal.addEventListener('abort',()=>{R.aborted++;reject(new DOMException('aborted','AbortError'));}));
    if(a instanceof Error)return Promise.reject(a);
    return Promise.resolve(Object.assign({agent:name,provider:'claude',mode:'cursor',events:[],before:'f:0',after:options.after??'f:1',has_older:true},a));
  };
  window.row=(id)=>({id,kind:'text',role:'assistant',text:id,ts:new Date().toISOString(),cursor_before:'f:0',cursor_after:'f:1'});
  0;"""


# "At once": well under the plain 4 s interval. Not tighter: this Mac runs
# other work, and one run took 893 ms for a read due at once.
BOUND_MS = 2000


def open_with(js, answer):
    """Reopen the reader with `answer(options, read, n)` as the fake server.

    The fixture's next roster poll may replace its hand-made pane, which
    closes this reader mid-test; not under test, so the roster poll is parked."""
    js("""if(!window.rosterParked){window.rosterParked=true;const f0=window.fetch;
      window.fetch=(u,...a)=>String(u).startsWith('/telemetry/agents')?new Promise(()=>{}):f0(u,...a);}0""")
    js('conversationView.close();' + HARNESS + 'R.answer=' + answer + ';conversationView.open();0')


def gap_after(js, wait, index):
    """ms between read `index` and read `index+1` (waits up to 6 s)."""
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        if js('R.reads.length') > index + 1:
            return js(f'R.reads[{index + 1}].at-R.reads[{index}].at')
        time.sleep(.05)
    return None


NOW, GAP, INTERVAL = (0, 600), (150, 900), (3500, 5000)

ROWS = [
    # name, answer(options, read, n) for reads after the first, expected gap after read 1
    ('opened, the server can hold', "(o,r,n)=>n===1?{hold:true,events:[row('o1')]}:'hold'", NOW),
    ('opened, no hold support (fresh, an old server)', "(o,r,n)=>({events:n===1?[row('o1')]:[]})", INTERVAL),
    ('slot answer without new rows', "(o,r,n)=>n===1?{hold:true,events:[row('o1')]}:n===2?{hold:true,slot:true,unchanged:true}:'hold'", NOW),
    ('slot answer with new rows', "(o,r,n)=>n===1?{hold:true,events:[row('o1')]}:n===2?{hold:true,slot:true,events:[row('n2')]}:'hold'", GAP),
    ('the server refused a slot (its cap)', "(o,r,n)=>n===1?{hold:true,events:[row('o1')]}:n===2?{hold:true,unchanged:true}:'hold'", INTERVAL),
    ('a catch-up page from a slot', "(o,r,n)=>n===1?{hold:true,events:[row('o1')]}:n===2?{hold:true,slot:true,has_newer:true,events:[row('c2')]}:'hold'", NOW),
    ('a catch-up page without a slot', "(o,r,n)=>n===1?{hold:true,events:[row('o1')]}:n===2?{hold:true,has_newer:true,events:[row('c2')]}:'hold'", INTERVAL),
    ('a failed read', "(o,r,n)=>n===1?{hold:true,events:[row('o1')]}:n===2?Object.assign(new Error('dashboard'),{code:'dashboard_unavailable'}):'hold'", INTERVAL),
]


@pytest.mark.parametrize('name,answer,expected', ROWS, ids=[r[0] for r in ROWS])
def test_next_request_after_an_answer(cockpit, name, answer, expected):  # noqa: F811
    js, wait, client = prepare(cockpit, 'claude')
    open_with(js, answer)
    # Read 1 is the opening read; the gap measured is after the answer to read 2
    # (or after read 1 for the opening rows).
    index = 0 if name.startswith('opened') else 1
    gap = gap_after(js, wait, index)
    lo, hi = expected
    assert gap is not None and lo <= gap <= hi, (name, gap, js('R.reads'))


def holding(js, wait):
    open_with(js, "(o,r,n)=>n===1?{hold:true,events:[row('o1')]}:o.before?{hold:true,events:[row('older1')],has_older:false}:'hold'")
    wait('R.reads.some(r=>r.wait===25)')


def test_a_slow_user_operation_keeps_holds_off_until_it_ends(cockpit):  # noqa: F811
    """RockyGuericke r5: a 2 s POST. No hold may restart before it settles."""
    js, wait, client = prepare(cockpit, 'claude')
    holding(js, wait)
    js("""window.slowDone=null;const slow=OrreryConversation.trackFetch(()=>new Promise(r=>setTimeout(()=>{slowDone=performance.now();r(new Response('{}'));},2000)));
      window.n0=R.reads.length;slow('/telemetry/open-url',{method:'POST',body:'{}'});0""")
    wait('R.aborted===1')
    time.sleep(1.5)
    assert js('R.reads.length') == js('n0')                       # nothing during the operation
    wait('slowDone!==null&&R.reads.length>n0')
    assert 0 <= js('R.reads[n0].at-slowDone') <= BOUND_MS              # at once after it


def test_overlapping_operations_resume_after_the_last(cockpit):  # noqa: F811
    js, wait, client = prepare(cockpit, 'claude')
    holding(js, wait)
    js("""window.ends=[];const op=ms=>OrreryConversation.trackFetch(()=>new Promise(r=>setTimeout(()=>{ends.push(performance.now());r(new Response('{}'));},ms)));
      window.n0=R.reads.length;op(800)('/telemetry/open-ghostty',{method:'POST'});op(1600)('/telemetry/reveal-path',{method:'POST'});0""")
    wait('ends.length===2&&R.reads.length>n0')
    assert js('R.reads[n0].at') >= js('ends[1]')                  # not after the first one


def test_another_tabs_operation_keeps_this_tabs_holds_off(cockpit):  # noqa: F811
    js, wait, client = prepare(cockpit, 'claude')
    holding(js, wait)
    js("window.other=new BroadcastChannel('orrery-history-holds');window.n0=R.reads.length;other.postMessage({type:'begin',id:'tab-x:1'});0")
    wait('R.aborted===1')
    time.sleep(1.0)
    assert js('R.reads.length') == js('n0')
    js("window.t1=performance.now();other.postMessage({type:'end',id:'tab-x:1'});0")
    wait('R.reads.length>n0')
    assert js('R.reads[n0].at-t1') <= BOUND_MS


def test_load_earlier_then_latest_returns_to_holding_at_once(cockpit):  # noqa: F811
    """WintryLovelace r5: Load earlier while held → Latest → the next held poll at once, not 4 s."""
    js, wait, client = prepare(cockpit, 'claude')
    holding(js, wait)
    js("reader.querySelector('.conversation-older').click()")
    wait("R.reads.some(r=>r.before)")
    wait("reader.querySelector('[data-event-id=older1]')!==null")
    js("window.olderAt=R.reads.find(r=>r.before).at;reader.querySelector('.conversation-latest').click();0")
    wait("R.reads.filter(r=>r.wait===25&&r.at>olderAt).length>=1")
    assert js("R.reads.find(r=>r.wait===25&&r.at>olderAt).at-olderAt") <= 1000


def test_hidden_then_visible(cockpit):  # noqa: F811
    js, wait, client = prepare(cockpit, 'claude')
    holding(js, wait)
    js("window.tabHidden=true;Object.defineProperty(document,'hidden',{configurable:true,get:()=>tabHidden});window.n0=R.reads.length;document.dispatchEvent(new Event('visibilitychange'));0")
    wait('R.aborted===1')
    time.sleep(1.0)
    assert js('R.reads.length') == js('n0')
    js("window.t1=performance.now();tabHidden=false;document.dispatchEvent(new Event('visibilitychange'));0")
    wait('R.reads.length>n0')
    assert js('R.reads[n0].at-t1') <= BOUND_MS and js('R.reads[n0].wait') == 25


def test_what_counts_as_a_user_operation(cockpit):  # noqa: F811
    js, wait, client = prepare(cockpit, 'claude')
    cases = {
        "['/telemetry/open-url',{method:'POST'}]": True,
        "['/telemetry/spawn',{method:'POST'}]": True,
        "['/api/exit',{method:'POST'}]": True,
        "['/telemetry/conversation/reveal',{method:'POST'}]": True,
        "['/telemetry/clipboard/files']": True,
        "['/telemetry/conversation/preview?ref=x']": True,
        "['/telemetry/path-probe',{method:'POST'}]": False,     # the terminal hover, not asked for
        "['/telemetry/conversation?agent=x']": False,           # History's own poll
        "['/telemetry/agents?scope=live']": False,              # a periodic poll
        "['/api/jump',{method:'POST'}]": False,                 # not from the cockpit page itself
        "['https://example.invalid/x',{method:'POST'}]": False, # another origin
    }
    for args, expected in cases.items():
        assert js(f'OrreryConversation.userRequest(...{args})') is expected, args
    # From the NETWORK frame: the dashboard's actions, by name. Not its automatic error report.
    frame = {'/api/jump': True, '/api/kill': True, '/api/exit': True, '/api/annotate': True,
             '/api/spawn': True, '/api/reactivate': True, '/api/jserr': False,
             '/telemetry/path-probe': False, '/telemetry/open-url': False}
    for path, expected in frame.items():
        assert js(f"OrreryConversation.userRequest({json.dumps(path)},{{method:'POST'}},{{frame:true}})") is expected, path
    assert js("OrreryConversation.userRequest('/api/jump',{},{frame:true})") is False   # a GET


def test_the_hover_probe_does_not_end_holds(cockpit):  # noqa: F811
    js, wait, client = prepare(cockpit, 'claude')
    holding(js, wait)
    js("fetch('/telemetry/path-probe',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}).catch(()=>{});0")
    time.sleep(.5)
    assert js('R.aborted') == 0


def test_frequent_operations_never_starve_a_reader(cockpit):  # noqa: F811
    """A pane over the server's cap (its slot refused) polls every pollMs. Operations
    every 200 ms re-plan it each time; that must never push its read back
    (r6: two tabs under a POST probe left one tab with no read for a minute)."""
    js, wait, client = prepare(cockpit, 'claude')
    open_with(js, "(o,r,n)=>n===1?{hold:true,events:[row('o1')]}:{hold:true,unchanged:true}")
    wait('R.reads.length>=2')                                      # the refused answer
    js("""window.n0=R.reads.length;window.t0=performance.now();window.opsTimer=setInterval(()=>{OrreryConversation.trackFetch(()=>new Promise(r=>setTimeout(()=>r(new Response('{}')),50)))('/telemetry/open-url',{method:'POST'});},200);0""")
    time.sleep(6)
    js('clearInterval(opsTimer)')
    during = js('R.reads.slice(n0).map(r=>r.at-t0)')
    assert during and during[0] <= 4600, during                    # the planned read still came


def test_an_operation_that_never_settles_expires(cockpit):  # noqa: F811
    """Own and another tab's operations end after OP_MAX_MS (90 s) even if
    their end never arrives (the fixture's clock is moved, not waited)."""
    js, wait, client = prepare(cockpit, 'claude')
    holding(js, wait)
    js("""window.expiries=[];const st=window.setTimeout;window.setTimeout=(f,ms,...a)=>{if(ms===90050)expiries.push(f);return st(f,ms,...a)};
      window.other=new BroadcastChannel('orrery-history-holds');
      OrreryConversation.trackFetch(()=>new Promise(()=>{}))('/telemetry/open-url',{method:'POST'});
      other.postMessage({type:'begin',id:'tab-x:9'});window.n0=R.reads.length;0""")
    wait('R.aborted===1&&expiries.length===2')
    time.sleep(1.0)
    assert js('R.reads.length') == js('n0')
    js('clock+=89000;expiries[0]();expiries[1]();0')                 # not yet expired
    time.sleep(.5)
    assert js('R.reads.length') == js('n0')
    js('window.t1=performance.now();clock+=1100;expiries.forEach(f=>f());0')
    wait('R.reads.length>n0')
    assert js('R.reads[n0].at-t1') <= BOUND_MS and js('R.reads[n0].wait') == 25


def test_the_network_frames_operations_stop_holds_and_end_with_its_document(cockpit):  # noqa: F811
    """CuriousPauling r6 P3-3: cockpit.html wraps the NETWORK frame's fetch.
    A dashboard action from the frame stops the holds; a navigation that
    leaves it unsettled ends it; the new document is wrapped again."""
    js, wait, client = prepare(cockpit, 'claude')
    holding(js, wait)
    client.call('Fetch.enable', patterns=[{'urlPattern': '*/api/jump*'}])   # the action never answers
    try:
        js("networkFrame.src='/conversation_source.js';0")
        wait("networkFrame.contentWindow.location.pathname==='/conversation_source.js'&&networkFrame.contentWindow.__orreryHoldsYield===true")
        js("window.n0=R.reads.length;networkFrame.contentWindow.fetch('/api/jserr',{method:'POST',body:'{}'}).catch(()=>{});0")
        time.sleep(.5)
        assert js('R.aborted') == 0                                         # not an operation
        js("networkFrame.contentWindow.fetch('/api/jump',{method:'POST',body:'{}'}).catch(()=>{});0")
        wait('R.aborted===1')
        time.sleep(1.0)
        assert js('R.reads.length') == js('n0')                            # held off while it is in flight
        js("window.t1=performance.now();networkFrame.src='/conversation_preview.js';0")
        wait('R.reads.length>n0')
        assert js('R.reads[n0].at-t1') <= BOUND_MS and js('R.reads[n0].wait') == 25
        wait("networkFrame.contentWindow.location.pathname==='/conversation_preview.js'&&networkFrame.contentWindow.__orreryHoldsYield===true")
        js("window.n1=R.reads.length;networkFrame.contentWindow.fetch('/api/kill',{method:'POST',body:'{}'}).catch(()=>{});0")
        wait('R.aborted===2')
    finally:
        client.call('Fetch.disable')


def test_a_tab_opened_later_learns_the_operations_in_flight(cockpit):  # noqa: F811
    """WintryLovelace r6: a later tab asks once ('who'); a tab with an
    operation in flight answers with its 'begin'. Here this page is the
    earlier tab and a channel stands in for the later one."""
    js, wait, client = prepare(cockpit, 'claude')
    holding(js, wait)
    js("""window.heard=[];window.later=new BroadcastChannel('orrery-history-holds');later.onmessage=({data})=>heard.push(data);
      OrreryConversation.trackFetch(()=>new Promise(()=>{}))('/telemetry/open-url',{method:'POST'});0""")
    wait("heard.filter(m=>m.type==='begin').length===1")
    js("heard.length=0;later.postMessage({type:'who'});0")
    wait("heard.some(m=>m.type==='begin')")
    assert js("heard.filter(m=>m.type==='begin').length") == 1
    # The asking side: the module posts 'who' once when it loads.
    assert "post({type:'who'})" in (ROOT / 'bridge/conversation_view.js').read_text()
