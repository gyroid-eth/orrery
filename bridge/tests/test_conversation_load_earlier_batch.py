"""One Load earlier reads several older pages (conversation_view.js readOlder).

A page stops at 200 events and at the server's scan window, and a tool call
and its result are one event each, so one 80-event page went back only a few
exchanges. One click now gathers about 300 events with up to four pages, and
the retention cap keeps two such clicks beside the first page.
"""
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'bridge/tests'))
from test_conversation_submissions import cockpit, prepare  # noqa: F401,E402

# A fake server: an older page ends at `before` and holds `limit` events
# (or `R.cap`, a scan window that ends the page early). Cursor `f:N` means
# event N; event 0 is the oldest. R.floor: no events before it.
# R.fail[k]: the k-th older read (1-based) fails with that code.
# R.hold[k]: the k-th older read waits until R.release() (it ignores abort,
# so only the reader's own generation check keeps its answer out).
HARNESS = """window.R={reads:[],cap:200,floor:0,stall:false,fail:{},hold:{},older:0,release:null};
  window.row=n=>({id:'e'+n,kind:n%5?'tool':'text',role:'assistant',text:'event '+n,ts:new Date().toISOString(),
    cursor_before:'f:'+n,cursor_after:'f:'+(n+1)});
  OrreryConversationSource.Source.prototype.read=function(name,options){
    const r={before:options.before??null,after:options.after??null,limit:options.limit??null};R.reads.push(r);
    if(options.after)return new Promise(()=>{});
    const k=options.before?++R.older:0;
    if(R.fail[k])return Promise.reject(Object.assign(new Error('fixture '+R.fail[k]),{code:R.fail[k]}));
    const end=options.before?Number(options.before.slice(2)):R.top;
    const size=R.stall&&options.before?0:Math.min(options.limit??80,options.before?R.cap:Infinity,end-R.floor);
    const events=Array.from({length:size},(_,i)=>row(end-size+i));
    const page={agent:name,provider:'claude',mode:'cursor',events,before:'f:'+(end-size),
      after:'f:'+R.top,has_older:end-size>R.floor,has_newer:false};
    if(R.hold[k])return new Promise(resolve=>{R.release=()=>resolve(page);});
    return Promise.resolve(page);
  };0"""


def reopen(js, wait, top=10000, **settings):
    js("""if(!window.rosterParked){window.rosterParked=true;const f0=window.fetch;
      window.fetch=(u,...a)=>String(u).startsWith('/telemetry/agents')?new Promise(()=>{}):f0(u,...a);}0""")
    js('conversationView.close();' + HARNESS + f';R.top={top};Object.assign(R,{json.dumps(settings)});conversationView.open();0')
    wait('reader.querySelectorAll(".conversation-event").length===' + str(min(80, top)))
    js('R.reads=R.reads.filter(r=>r.before);0')


def click(js, wait):
    js("window.clicked=R.reads.length;reader.querySelector('.conversation-older').click();0")
    wait('R.reads.filter(r=>r.before).length>clicked&&!reader.querySelector(".conversation-older").disabled')


def older_reads(js):
    return js('R.reads.filter(r=>r.before)')


def shown(js):
    return js("[...reader.querySelectorAll('.conversation-event')].map(e=>Number(e.dataset.eventId.slice(1)))")


def test_one_click_reads_300_events_in_two_pages(cockpit):  # noqa: F811
    js, wait, client = prepare(cockpit, 'claude')
    reopen(js, wait)
    click(js, wait)
    assert older_reads(js) == [dict(before='f:9920', after=None, limit=200), dict(before='f:9720', after=None, limit=100)]
    assert shown(js) == list(range(9620, 10000))      # in reading order, nothing lost
    assert not js("reader.querySelector('.conversation-older').hidden")


def test_a_scan_window_page_reads_up_to_four_pages(cockpit):  # noqa: F811
    js, wait, client = prepare(cockpit, 'claude')
    reopen(js, wait, cap=50)
    click(js, wait)
    assert [r['before'] for r in older_reads(js)] == ['f:9920', 'f:9870', 'f:9820', 'f:9770']
    assert len(shown(js)) == 80 + 200


def test_the_start_of_the_record_ends_the_click(cockpit):  # noqa: F811
    js, wait, client = prepare(cockpit, 'claude')
    reopen(js, wait, top=150)
    click(js, wait)
    assert len(older_reads(js)) == 1
    assert shown(js) == list(range(150))
    assert js("reader.querySelector('.conversation-older').hidden")


def test_a_cursor_that_does_not_move_ends_the_click(cockpit):  # noqa: F811
    js, wait, client = prepare(cockpit, 'claude')
    reopen(js, wait, stall=True)
    click(js, wait)
    assert len(older_reads(js)) == 1


def test_two_clicks_are_kept_and_the_third_releases_the_newest(cockpit):  # noqa: F811
    js, wait, client = prepare(cockpit, 'claude')
    reopen(js, wait)
    status = "reader.querySelector('.conversation-toolbar .conversation-status').textContent"
    click(js, wait)
    click(js, wait)
    assert len(shown(js)) == 80 + 300 + 300
    assert 'bounded' not in js(status)
    click(js, wait)
    assert shown(js) == list(range(9020, 9820))       # 800 kept; the newest 180 released
    assert 'bounded' in js(status)                    # the existing notice; Latest reloads


@pytest.mark.parametrize('code', ['record_too_large', 'dashboard_unavailable'])
def test_a_later_failure_keeps_the_pages_already_read(cockpit, code):  # noqa: F811
    js, wait, client = prepare(cockpit, 'claude')
    reopen(js, wait, cap=50, fail={'2': code})
    click(js, wait)
    assert shown(js) == list(range(9870, 10000))      # the first page is shown
    assert js("reader.querySelector('.conversation-retry').hidden")
    assert not js("reader.querySelector('.conversation-older').hidden")
    click(js, wait)                                   # the next click continues from it
    assert older_reads(js)[2]['before'] == 'f:9870'
    assert shown(js)[0] == 9670


def test_a_binding_failure_on_a_later_page_keeps_nothing(cockpit):  # noqa: F811
    js, wait, client = prepare(cockpit, 'claude')
    reopen(js, wait, cap=50, fail={'2': 'history_changed'})
    js("reader.querySelector('.conversation-older').click();0")
    wait("!reader.querySelector('.conversation-retry').hidden")
    assert shown(js) == []
    assert len(older_reads(js)) == 2


def test_a_conversation_switched_mid_click_reads_no_further_and_shows_nothing_old(cockpit):  # noqa: F811
    js, wait, client = prepare(cockpit, 'claude')
    reopen(js, wait, hold={'1': True})
    js("reader.querySelector('.conversation-older').click();0")
    wait('R.release!==null')
    # Close and reopen while the first older page is still on its way.
    js("conversationView.close();conversationView.open();0")
    wait('reader.querySelectorAll(".conversation-event").length===80')
    js('R.release();0')
    time.sleep(.4)
    assert len(older_reads(js)) == 1                  # no second page for the old click
    assert shown(js) == list(range(9920, 10000))      # nothing from the released page


@pytest.mark.skipif(shutil.which('node') is None, reason='node is not installed')
def test_source_sends_only_a_valid_limit():
    script = r"""
const {Source}=require(process.argv[1]);
(async()=>{
  const urls=[];
  const source=new Source(async url=>{urls.push(url);return {ok:true,json:async()=>({ok:true,agent:'A',events:[]})};});
  for(const limit of [200,1,0,201,1.5,'200',null])await source.read('A',{before:'f:1',limit});
  console.log(JSON.stringify(urls));
})().catch(e=>{console.error(e);process.exit(1)});
"""
    source = ROOT / 'bridge/conversation_source.js'
    result = subprocess.run(['node', '-e', script, str(source)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    base = '/telemetry/conversation?agent=A&before=f%3A1'
    assert json.loads(result.stdout) == [base + '&limit=200', base + '&limit=1'] + [base] * 5
