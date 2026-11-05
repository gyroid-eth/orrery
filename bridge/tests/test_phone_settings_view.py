"""Settings → Phone as drawn: phone_settings.js under node with a small fake
DOM and a fake /telemetry/mobile, plus the desktop history default as the
page actually runs it.

- A reader started by hand holds the port: the panel says so (MANUAL) instead
  of "OFF · Reader off", and offers no switch that would claim to stop it.
- Demo mode: the owner login, the phone address and the Serve URL are not put
  on the page at all (demo_mask hides only the user and host names).
- Desktop conversation history: on when never chosen, an explicit "0" stays.

Run from bridge/: ``python -m pytest tests/test_phone_settings_view.py``.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")

OWNER = "owner.name@example.test"
ORIGIN = "https://studio.tail-example.ts.net:9443"
DNS = "studio.tail-example.ts.net"

DOM = r"""
class Node{constructor(tag){this.tagName=tag;this.children=[];this._text='';this.className='';this.dataset={};
  this.hidden=false;this.disabled=false;this.checked=false;this.value='';this.listeners={};}
  append(...xs){for(const x of xs)this.children.push(typeof x==='string'?Object.assign(new Node('#text'),{_text:x}):x);}
  replaceChildren(){this.children=[];}
  set textContent(v){this._text=String(v);this.children=[];}
  get textContent(){return this._text+this.children.map(c=>c.textContent).join(' ');}
  addEventListener(t,f){this.listeners[t]=f;}
  setAttribute(k,v){this[k]=String(v);}
  scrollIntoView(){EVENTS.push('scroll:'+this.id);}
  focus(){EVENTS.push('focus:'+this.id);}
  all(){return [this,...this.children.flatMap(c=>c.all())];}
  values(){return this.all().filter(n=>n.tagName==='input').map(n=>n.value+' '+n.placeholder).join(' ');}
}
const byId={},EVENTS=[],PUTS=[];
for(const id of ['phoneSettings','phoneBadge','settingsPopover'])byId[id]=new Node('div');
global.document={getElementById:id=>byId[id]||byId.phoneSettings.all().find(n=>n.id===id)||null,createElement:t=>new Node(t)};
global.window=global;
"""

RUN = r"""
global.fetch=async(_,init)=>{
  if(init.method==='PUT'){const body=JSON.parse(init.body);PUTS.push(body);
    for(const k of ['access','send','owner_login','public_origin'])if(k in body)STATE.settings[k]=body[k];
    if(body.policy_reviewed)STATE.settings.policy_reviewed_at='2026-11-05T01:02:03Z';}
  return {json:async()=>JSON.parse(JSON.stringify(STATE))};
};
const tick=()=>new Promise(r=>setTimeout(r,5));
global.navigator={clipboard:{writeText(){}}};
require(SCRIPT);
(async()=>{
  await window.OrreryPhoneSettings.refresh();
  const missing=[];
  for(const step of STEPS){
    const all=byId.phoneSettings.all();
    if(step==='@open'){byId.settingsPopover.listeners.toggle({newState:'open'});await tick();continue;}
    if(step[0]==='='){const [id,...v]=step.slice(1).split('=');all.find(n=>n.id===id).value=v.join('=');continue;}
    if(step[0]==='#'){const input=all.find(n=>n.id===step.slice(1));input.checked=!input.checked;input.listeners.change();await tick();continue;}
    const button=all.find(n=>n.tagName==='button'&&n.textContent===step);
    if(button){button.listeners.click();await tick();}else missing.push(step);
  }
  const root=byId.phoneSettings,inputs=Object.fromEntries(root.all().filter(n=>n.id).map(n=>[n.id,{disabled:n.disabled,checked:n.checked}]));
  const order=root.all().map(n=>n.id||(n.className==='phone-note'?'note':'')).filter(Boolean);
  const note=root.all().find(n=>n.className==='phone-note');
  console.log(JSON.stringify({missing,badge:byId.phoneBadge.textContent,text:root.textContent,fields:root.values(),inputs,
    order,note:note?note.textContent:null,events:EVENTS,puts:PUTS,reloads:global.RELOADS||[]}));
})();
"""


def state(**over):
    relay = {"job": "loaded", "listening": True, "manual": False, "python_missing": False, "port": 8781}
    relay.update(over.pop("relay", {}))
    settings = {"access": True, "send": True, "owner_login": OWNER, "public_origin": ORIGIN,
                "policy_reviewed_at": "2026-11-05T01:02:03Z"}
    settings.update(over.pop("settings", {}))
    tailscale = {"found": True, "signed_in": True, "dns_name": DNS, "login": OWNER, "serve": "ok", "funnel": False}
    tailscale.update(over.pop("tailscale", {}))
    return {"ok": True, "error": None, "settings": settings, "relay": relay, "tailscale": tailscale,
            "effective": {"read": True, "history": True, "send": True}, "saved": True,
            "suggest": {"owner_login": OWNER, "public_origin": ORIGIN}, "cockpit": {"send": True}, **over}


def draw(value, *, demo=False, steps=(), demo_reload=False):
    script = (DOM + f"const STATE={json.dumps(value)};const STEPS={json.dumps(list(steps))};"
              + f"const SCRIPT={json.dumps(str(ROOT / 'phone_settings.js'))};"
              + ("global.OrreryDemo={on:true};" if demo else "")
              + ("global.RELOADS=[];global.OrreryDemo.reloadFor=v=>RELOADS.push(v);" if demo and demo_reload else "")
              + RUN)
    done = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_hand_started_reader_is_shown_as_manual_not_off():
    view = draw(state(settings={"access": False}, relay={"job": "absent", "listening": True, "manual": True}))
    assert view["badge"] == "MANUAL"
    assert "Reader off" not in view["text"]
    assert "not started from Settings" in view["text"] and "127.0.0.1:8781" in view["text"]
    assert view["inputs"]["phoneAccess"]["disabled"] is True


def test_settings_reader_is_not_mistaken_for_a_manual_one():
    view = draw(state())
    assert view["badge"] == "ON" and "not started from Settings" not in view["text"]
    assert view["inputs"]["phoneAccess"]["disabled"] is False


def test_status_says_when_the_readers_python_is_gone():
    view = draw(state(relay={"listening": False, "python_missing": True}))
    assert "Python" in view["text"] and "off and on" in view["text"]


@pytest.mark.parametrize("case", ["ready", "setup", "first", "edit"])
def test_demo_mode_puts_no_owner_address_or_serve_url_on_the_page(case):
    value, steps = state(), ()
    if case == "setup":
        value = state(tailscale={"serve": "missing"}, settings={"policy_reviewed_at": None})
    elif case == "first":
        value = state(settings={"access": False, "owner_login": "", "public_origin": ""})
        steps = ("#phoneAccess",)
    elif case == "edit":
        steps = ("Change owner or address",)
    shown = draw(value, demo=True, steps=steps)
    plain = draw(value, demo=False, steps=steps)
    page = shown["text"] + " " + shown["fields"]
    for secret in (OWNER, "owner.name", ORIGIN, DNS, "tail-example"):
        assert secret not in page, (case, secret)
    # without demo mode the same panel does show them, so the test can see them
    assert OWNER in plain["text"] + " " + plain["fields"] and plain["missing"] == []
    assert "hidden in demo mode" in shown["text"]
    if case == "edit":
        assert shown["missing"] == ["Change owner or address"]


def test_first_setup_in_demo_mode_offers_no_fields_to_fill():
    value = state(settings={"access": False, "owner_login": "", "public_origin": ""})
    view = draw(value, demo=True, steps=("#phoneAccess",))
    assert "phoneOwner" not in view["inputs"] and "phoneAddress" not in view["inputs"]


def test_editing_owner_after_review_says_the_review_is_asked_again():
    view = draw(state(), steps=("Change owner or address",))
    assert "step 4 again" in view["text"]


# --- the line under the Phone access switch --------------------------------

FIRST = {"access": False, "owner_login": "", "public_origin": "", "policy_reviewed_at": None}


def under_the_switch(view):
    order = view["order"]
    return order.index("phoneAccess") < order.index("phoneSwitchNote") < order.index("phoneSend")


def test_demo_mode_first_press_says_to_turn_off_demo_mode_right_under_the_switch():
    view = draw(state(settings=FIRST), demo=True, steps=("#phoneAccess",), demo_reload=True)
    assert "Turn off demo mode to set up phone access (once)" in view["note"]
    assert "switch it on and off in demo mode" in view["note"]
    assert under_the_switch(view)
    assert view["puts"] == [] and view["badge"] == "OFF" and view["inputs"]["phoneAccess"]["checked"] is False
    pressed = draw(state(settings=FIRST), demo=True, steps=("#phoneAccess", "Turn off demo mode"), demo_reload=True)
    assert pressed["reloads"] == [False] and pressed["missing"] == []


def test_demo_mode_first_press_does_not_move_the_page_or_the_cursor():
    assert draw(state(settings=FIRST), demo=True, steps=("#phoneAccess",))["events"] == []


def test_reopening_settings_drops_the_note_and_the_steps_it_opened():
    for demo in (False, True):
        view = draw(state(settings=FIRST), demo=demo, steps=("#phoneAccess", "@open"))
        assert view["note"] is None
        assert "Tailscale signed in" not in view["text"]


def test_second_press_keeps_what_was_typed_in_step_two():
    typed = "https://other.example.ts.net:9443"
    view = draw(state(settings=FIRST), steps=("#phoneAccess", "=phoneAddress=" + typed, "#phoneAccess"))
    assert typed in view["fields"]
    assert view["events"] == ["scroll:phoneStepOwner", "focus:phoneOwner"] * 2
    assert view["puts"] == [] and view["inputs"]["phoneAccess"]["checked"] is False


def test_first_press_without_tailscale_sign_in_points_to_step_one():
    view = draw(state(settings=FIRST, tailscale={"signed_in": False}), steps=("#phoneAccess",))
    assert "sign in to Tailscale" in view["note"] and "step 1 below" in view["note"]
    assert "step 2" not in view["note"]
    assert view["events"] == [] and view["puts"] == []
    assert "Tailscale is installed but not signed in" in view["text"]


def test_nothing_is_said_under_the_switch_before_it_is_pressed():
    assert draw(state(settings=FIRST), demo=True)["note"] is None
    assert draw(state(settings=FIRST))["note"] is None


def test_first_press_points_to_step_two_and_puts_the_cursor_there():
    view = draw(state(settings=FIRST), steps=("#phoneAccess",))
    assert "step 2 below" in view["note"] and "Confirm and turn on" in view["note"]
    assert under_the_switch(view)
    assert view["events"] == ["scroll:phoneStepOwner", "focus:phoneOwner"]
    assert view["puts"] == [] and view["inputs"]["phoneAccess"]["checked"] is False
    assert "Turn off demo mode" not in view["text"]


def test_after_confirm_the_first_press_note_gives_way_to_what_is_still_off():
    view = draw(state(settings=FIRST), steps=("#phoneAccess", "Confirm and turn on"))
    assert view["puts"] and view["puts"][0]["access"] is True and view["missing"] == []
    assert "step 2 below" not in view["note"]
    assert "Conversation and Send from phone stay off until step 4" in view["note"]


def test_on_before_the_policy_review_says_conversation_and_send_are_off():
    view = draw(state(settings={"policy_reviewed_at": None}))
    assert view["badge"] == "SETUP"
    assert "Conversation and Send from phone stay off until step 4 below" in view["note"]
    assert under_the_switch(view)


@pytest.mark.parametrize("case", ["reviewed", "off", "manual"])
def test_no_policy_line_when_it_would_not_be_true(case):
    value = {"reviewed": state(),
             "off": state(settings={"access": False, "policy_reviewed_at": None}),
             "manual": state(settings={"policy_reviewed_at": None},
                             relay={"job": "absent", "listening": True, "manual": True})}[case]
    assert draw(value)["note"] is None


# --- desktop conversation history default, as cockpit.html runs it ----------

def bootstrap():
    html = (ROOT / "cockpit.html").read_text()
    match = re.search(r"const key='oc-term-conversation-enabled'.*?const enabled=[^\n]*\n", html, re.S)
    assert match, "the history bootstrap moved"
    return match.group(0)


@pytest.mark.parametrize("stored,expected", [(None, True), ("0", False), ("1", True)])
def test_desktop_history_is_on_unless_this_browser_chose_off(stored, expected):
    script = ("const store=new Map(" + json.dumps([] if stored is None else [["oc-term-conversation-enabled", stored]]) + ");"
              "global.localStorage={getItem:k=>store.has(k)?store.get(k):null,setItem:(k,v)=>store.set(k,String(v))};"
              "global.document={getElementById:()=>null};"
              + bootstrap() + "console.log(JSON.stringify({on:enabled(),stored:store.get(key)}));")
    done = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    value = json.loads(done.stdout)
    assert value["on"] is expected
    assert value["stored"] == ("1" if stored is None else stored)
