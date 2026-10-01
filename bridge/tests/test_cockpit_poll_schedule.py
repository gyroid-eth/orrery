"""The cockpit's polls wait for the last answer; the graph stops in a hidden tab (2026-10-01).

A fixed setInterval asked /telemetry/graph again every 6 s whether or not the
last request had come back, so a slow dashboard computed several graphs at
once and used several cores. Now each poll has one request out at a time and
keeps the old pace when answers are quick. The graph poll stops in a hidden
tab and asks again the moment the tab is shown; the agents and mail polls keep
running there (a pause would misorder the roster and lose mail older than the
dashboard's five-minute window). These run the cockpit's own poll scheduling
under node, with a fake clock, a fake document and stand-in poll functions.

Run from bridge/: ``python -m pytest tests/test_cockpit_poll_schedule.py``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SOURCES = Path(os.environ.get("ORRERY_BRIDGE_SOURCES", ROOT))
COCKPIT = SOURCES / "cockpit.html"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")

# Everything from the poll scheduling to the end of the main script.
BLOCK = r"(?:/\* A poll sends one request at a time.*?\*/\n)?(?:function startPoll|if\(soloSession\)\{pollAgents).*?(?=</script>)"

HARNESS = r"""
let now=0,nextId=1;const timers=new Map();Date.now=()=>now;
function setTimeout(fn,ms){const id=nextId++;timers.set(id,{at:now+(ms||0),fn});return id;}
function clearTimeout(id){timers.delete(id);}
function setInterval(fn,ms){const id=nextId++;timers.set(id,{at:now+ms,fn,every:ms});return id;}
async function flush(){for(let i=0;i<50;i++)await Promise.resolve();}
async function advance(ms){
  const end=now+ms;
  for(;;){
    let best=null;
    for(const [id,t] of timers)if(t.at<=end&&(best===null||t.at<timers.get(best).at))best=id;
    if(best===null)break;
    const t=timers.get(best);now=t.at;
    if(t.every)t.at+=t.every;else timers.delete(best);
    t.fn();await flush();
  }
  now=end;await flush();
}
const listeners=[];
const document={hidden:false,addEventListener(type,fn){if(type==='visibilitychange')listeners.push(fn);}};
async function setHidden(h){document.hidden=h;listeners.forEach(fn=>fn());await flush();}
// mode: 'ok' answers at once, 'slow' waits for answer(kind), 'fail' rejects
const calls=[],waiting={graph:[],agents:[],mail:[]},mode={graph:'ok',agents:'ok',mail:'ok'};
function stand(kind){return function(){
  calls.push([kind,now]);
  if(mode[kind]==='fail')return Promise.reject(new Error(kind+' failed'));
  if(mode[kind]==='502')return Promise.resolve(false);
  if(mode[kind]==='slowfail')return new Promise((res,rej)=>waiting[kind].push(()=>rej(new Error('cut'))));
  if(mode[kind]==='slow502')return new Promise(res=>waiting[kind].push(()=>res(false)));
  if(mode[kind]==='slow')return new Promise(res=>waiting[kind].push(res));
  return Promise.resolve();};}
// the graph stand-in fills the lineage on a good answer, as pollGraph does
let lineageParent=new Map(),lineageAnswer=[['Kid','Mom']];
const graphStand=stand('graph');
const pollGraph=()=>graphStand().then(ok=>{if(ok!==false)lineageParent=new Map(lineageAnswer);return ok;});
const pollAgents=stand('agents'),pollMail=stand('mail');
async function answer(kind){waiting[kind].splice(0).forEach(res=>res());await flush();}
const count=kind=>calls.filter(c=>c[0]===kind).length;
"""


def run(steps: str, *, setup: str = "", solo: bool = False):
    html = COCKPIT.read_text(encoding="utf-8")
    match = re.search(BLOCK, html, re.DOTALL)
    assert match, "missing the poll scheduling in cockpit.html"
    script = "\n".join([
        HARNESS,
        f"const soloSession={json.dumps(solo)};",
        setup,
        match.group(0),
        f"(async()=>{{await flush();\n{steps}\n}})().then(r=>console.log(JSON.stringify(r)));",
    ])
    done = subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=False, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


# ---------------------------------------------------------------- positive

def test_the_first_round_asks_for_the_lineage_before_the_roster():
    r = run("""
      const before=calls.map(c=>c[0]).sort();
      await advance(1000);await answer('graph');
      return {before,after:calls.map(c=>c[0]).sort()};""",
            setup="mode.graph='slow';")
    assert r == {"before": ["graph", "mail"], "after": ["agents", "graph", "mail"]}


def test_quick_answers_keep_the_old_pace():
    r = run("await advance(12000);return {graph:count('graph'),agents:count('agents'),mail:count('mail')};")
    # at 0 s, then every 6 / 3 / 4 s, as the fixed intervals did
    assert r == {"graph": 3, "agents": 5, "mail": 4}


def test_the_pace_counts_from_when_a_request_started():
    """An answer that takes 2 s must not push the next request to 8 s: the
    screen would show older lineage than before."""
    r = run("""
      await advance(2000);await answer('graph');await advance(4000);
      return calls.filter(c=>c[0]==='graph').map(c=>c[1]);""",
            setup="mode.graph='slow';")
    assert r == [0, 6000]


def test_a_slow_answer_is_waited_for_then_asked_again_at_once():
    r = run("""
      await advance(60000);const during=count('graph');
      await answer('graph');await advance(0);
      return {during,after:count('graph'),last:calls.filter(c=>c[0]==='graph').pop()[1]};""",
            setup="mode.graph='slow';")
    assert r["during"] == 1                    # one request in 60 s while the first is still out
    assert r["after"] == 2 and r["last"] == 60000   # the next one as soon as it answered


def test_a_hidden_tab_stops_the_graph_and_asks_at_once_when_shown():
    r = run("""
      await setHidden(true);const graphAt=count('graph');
      await advance(121000);const whileHidden=count('graph')-graphAt;   // 121 s: off the agents/mail beat
      await setHidden(false);const shownAt=now;
      return {whileHidden,shown:calls.filter(c=>c[1]===shownAt).map(c=>c[0])};""")
    assert r["whileHidden"] == 0
    assert sorted(r["shown"]) == ["agents", "graph", "mail"]
    assert r["shown"].index("graph") < r["shown"].index("agents")


def test_a_hidden_tab_keeps_the_agents_and_mail_at_their_pace():
    r = run("""
      await advance(500);await setHidden(true);const a=count('agents'),m=count('mail');
      await advance(12000);return {agents:count('agents')-a,mail:count('mail')-m};""")
    assert r == {"agents": 4, "mail": 3}


def test_a_tab_hidden_while_the_graph_is_out_does_not_ask_again_until_shown():
    r = run("""
      await setHidden(true);await answer('graph');
      await advance(60000);const whileHidden=count('graph');
      await setHidden(false);return {whileHidden,shown:count('graph')};""",
            setup="mode.graph='slow';")
    assert r == {"whileHidden": 1, "shown": 2}


def test_showing_the_tab_while_a_request_is_out_does_not_send_a_second():
    r = run("""
      await setHidden(true);await setHidden(false);const shown=count('graph');
      await answer('graph');return {shown};""",
            setup="mode.graph='slow';")
    assert r == {"shown": 1}


def test_hiding_and_showing_again_does_not_double_the_pace():
    r = run("""
      await advance(1000);await setHidden(true);await setHidden(false);const n=count('graph');
      await advance(24000);return {n,later:count('graph')-n};""")
    # asked again on showing (1 s), then every 6 s: 7, 13, 19, 25
    assert r == {"n": 2, "later": 4}


def test_a_failing_poll_keeps_polling():
    r = run("await advance(12000);return count('agents');", setup="mode.agents='fail';")
    assert r == 5


def test_a_popped_out_window_polls_only_the_agents():
    r = run("""
      await advance(9000);const seen=[...new Set(calls.map(c=>c[0]))];
      return {seen,n:calls.length};""", solo=True)
    assert r == {"seen": ["agents"], "n": 4}


def test_a_timed_out_request_waits_a_full_interval_before_the_next():
    """The backend gives up after 6 s but the dashboard may still be computing;
    asking again at once would stack a second computation on the first."""
    r = run("""
      await advance(6000);await answer('graph');await advance(5999);const before=count('graph');
      await advance(1);return {before,after:count('graph'),at:now};""",
            setup="mode.graph='slow502';")
    assert r == {"before": 1, "after": 2, "at": 12000}


def test_a_request_that_throws_late_also_waits_a_full_interval():
    r = run("""
      await advance(6000);await answer('graph');await advance(5999);const before=count('graph');
      await advance(1);return {before,after:count('graph')};""",
            setup="mode.graph='slowfail';")
    assert r == {"before": 1, "after": 2}


def test_an_offline_dashboard_is_asked_again_at_the_old_pace():
    r = run("await advance(12000);return count('agents');", setup="mode.agents='502';")
    assert r == 5    # fails at once, so 3 s from its end is 3 s from its start


# ---------------------------------------------------------------- the requests themselves

POLLS = r"async function pollGraph\(\)\{.*?\n\}\n|async function pollMail\(\)\{.*?\n\}\n"
FETCH = r"""
const document={hidden:false,dispatchEvent(){}};const networkOverlay={classList:{contains:()=>false}};
class CustomEvent{constructor(t,o){this.type=t;this.detail=o&&o.detail;}}
let lineageParent=new Map([['Kid','Mom']]);const seenMsg=new Set();let mailSince=0;const mailBacklog=[];
const asked=[];let reply;
function fetch(url,opts){asked.push(url);return Promise.resolve(reply);}
const json=(status,body)=>({ok:status>=200&&status<300,status,json:()=>Promise.resolve(body)});
"""


def run_polls(steps: str):
    html = COCKPIT.read_text(encoding="utf-8")
    parts = [m.group(0) for m in re.finditer(POLLS, html, re.DOTALL)]
    assert len(parts) == 2, "missing pollGraph / pollMail in cockpit.html"
    script = "\n".join([FETCH, *parts, f"(async()=>{{\n{steps}\n}})().then(r=>console.log(JSON.stringify(r)));"])
    done = subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=False, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_requests_ask_the_same_endpoints_as_before():
    """Same URLs, so the dashboard computes and returns the same payloads."""
    r = run_polls("""
      reply=json(200,{spawn:[]});await pollGraph();
      reply=json(200,{ok:true,messages:[]});await pollMail();return asked;""")
    assert r == ["/telemetry/graph?all=1&spawn_only=1", "/telemetry/messages?since=0&limit=40"]


def test_a_graph_answer_replaces_the_lineage():
    r = run_polls("""
      reply=json(200,{spawn:[{source:'Dad',target:'Kid'}]});const ok=await pollGraph();
      return {ok:ok!==false,lineage:[...lineageParent]};""")
    assert r == {"ok": True, "lineage": [["Kid", "Dad"]]}


def test_a_502_keeps_the_lineage_and_counts_as_a_failure():
    """Before, the backend's 502 body was read as a graph with no spawn edges,
    and every lineage colour went away until the next good answer."""
    r = run_polls("""
      reply=json(502,{error:'dashboard offline'});const ok=await pollGraph();
      return {ok,lineage:[...lineageParent]};""")
    assert r == {"ok": False, "lineage": [["Kid", "Mom"]]}


def test_a_502_from_mail_counts_as_a_failure():
    r = run_polls("reply=json(502,{error:'dashboard offline'});return await pollMail();")
    assert r is False


AGENTS_HARNESS = r"""
const rosterTag={hidden:true,textContent:''},agentDot={className:'dot open'},removed=[];
const tiles=new Map([['Kid',{remove(){removed.push('Kid');}}]]);
let reply;const json=(status,body)=>({ok:status>=200&&status<300,status,headers:{get:()=>null},
  json:()=>Promise.resolve(body)});
const known={rosterTag,agentDot,tiles,fetch:()=>Promise.resolve(reply)};
// everything else pollAgents touches is a do-nothing stand-in
const nothing=new Proxy(function(){},{get:()=>nothing,apply:()=>nothing});
const env=new Proxy(known,{has:(t,k)=>k in t||!(k in globalThis),
  get:(t,k)=>typeof k==='symbol'?undefined:k in t?t[k]:nothing});   // no Symbol.unscopables
with(env){globalThis.pollAgentsUnderTest=__POLL__;}
const pollAgents=globalThis.pollAgentsUnderTest;
"""


def run_agents(steps: str):
    html = COCKPIT.read_text(encoding="utf-8")
    body = re.search(r"async function pollAgents\(\)\{.*?\n\}\n", html, re.DOTALL).group(0)
    poll = body.replace("async function pollAgents(){", "async function(){", 1)
    script = AGENTS_HARNESS.replace("__POLL__", poll) + f"(async()=>{{\n{steps}\n}})().then(r=>console.log(JSON.stringify(r)));"
    done = subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=False, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_a_slow_dashboard_keeps_the_roster_and_says_slow_not_offline():
    """Review P3: the backend gave up after 6 s; the dashboard is still there."""
    r = run_agents("""
      reply=json(502,{error:'dashboard slow'});const ok=await pollAgents();
      return {ok,tag:rosterTag.textContent,shown:!rosterTag.hidden,dot:agentDot.className,removed};""")
    assert r == {"ok": False, "tag": "dashboard slow", "shown": True,
                 "dot": "dot open", "removed": []}


def test_a_busy_dashboard_is_slow_too_not_offline():
    """The dashboard answers 503 {"error":"busy","retry":true} at its wait limit
    (orrery-telemetry #166); the backend passes it through."""
    r = run_agents("""
      reply=json(503,{error:'busy',retry:true});const ok=await pollAgents();
      return {ok,tag:rosterTag.textContent,dot:agentDot.className,removed};""")
    assert r == {"ok": False, "tag": "dashboard slow", "dot": "dot open", "removed": []}


def test_a_503_keeps_the_lineage_and_counts_as_a_failure():
    r = run_polls("""
      reply=json(503,{error:'busy',retry:true});const ok=await pollGraph();
      return {ok,lineage:[...lineageParent]};""")
    assert r == {"ok": False, "lineage": [["Kid", "Mom"]]}


def test_an_offline_dashboard_keeps_the_roster_and_says_offline():
    """Before, the 502 body had no agents, so every tile was removed."""
    r = run_agents("""
      reply=json(502,{error:'dashboard offline'});const ok=await pollAgents();
      return {ok,tag:rosterTag.textContent,dot:agentDot.className,removed};""")
    assert r == {"ok": False, "tag": "dashboard offline", "dot": "dot error", "removed": []}


# ---------------------------------------------------------------- negative

def test_a_page_loaded_hidden_takes_its_first_lineage_and_then_waits():
    """Review P2-1: a tab opened in the background must show the right
    lineage colours the moment it is brought forward."""
    r = run("""
      await advance(30000);const hidden=count('graph'),lineage=[...lineageParent];
      await setHidden(false);return {hidden,lineage,shown:count('graph')};""",
            setup="document.hidden=true;")
    assert r == {"hidden": 1, "lineage": [["Kid", "Mom"]], "shown": 2}


def test_a_hidden_tab_keeps_asking_for_the_graph_while_it_has_no_lineage():
    """As before the change: no lineage yet (a failed first answer, or no
    spawns at all) and the graph is asked for even in a hidden tab."""
    r = run("await advance(12000);return count('graph');",
            setup="document.hidden=true;lineageAnswer=[];")
    assert r == 3


def test_switching_back_within_a_second_does_not_ask_again():
    """Review P3: a request that started under a second ago is fresh enough;
    the usual pace goes on."""
    r = run("""
      await advance(500);await setHidden(true);await setHidden(false);
      const quick={graph:count('graph'),agents:count('agents'),mail:count('mail')};
      await advance(1000);await setHidden(true);await setHidden(false);
      const later={graph:count('graph'),agents:count('agents'),mail:count('mail')};
      await advance(4500);return {quick,later,paced:count('agents')};""")
    assert r["quick"] == {"graph": 1, "agents": 1, "mail": 1}
    assert r["later"] == {"graph": 2, "agents": 2, "mail": 2}   # 1.5 s after the first round
    assert r["paced"] == 3   # agents at 0, 1.5 (shown again), then 3 s from that: 4.5
