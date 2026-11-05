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
  all(){return [this,...this.children.flatMap(c=>c.all())];}
  values(){return this.all().filter(n=>n.tagName==='input').map(n=>n.value+' '+n.placeholder).join(' ');}
}
const byId={};
for(const id of ['phoneSettings','phoneBadge','settingsPopover'])byId[id]=new Node('div');
global.document={getElementById:id=>byId[id]||null,createElement:t=>new Node(t)};
global.window=global;
"""

RUN = r"""
global.fetch=async()=>({json:async()=>STATE});
global.navigator={clipboard:{writeText(){}}};
require(SCRIPT);
(async()=>{
  await window.OrreryPhoneSettings.refresh();
  const missing=[];
  for(const step of STEPS){
    const all=byId.phoneSettings.all();
    if(step[0]==='#'){const input=all.find(n=>n.id===step.slice(1));input.checked=!input.checked;input.listeners.change();continue;}
    const button=all.find(n=>n.tagName==='button'&&n.textContent===step);
    if(button)button.listeners.click();else missing.push(step);
  }
  const root=byId.phoneSettings,inputs=Object.fromEntries(root.all().filter(n=>n.id).map(n=>[n.id,{disabled:n.disabled,checked:n.checked}]));
  console.log(JSON.stringify({missing,badge:byId.phoneBadge.textContent,text:root.textContent,fields:root.values(),inputs}));
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


def draw(value, *, demo=False, steps=()):
    script = (DOM + f"const STATE={json.dumps(value)};const STEPS={json.dumps(list(steps))};"
              + f"const SCRIPT={json.dumps(str(ROOT / 'phone_settings.js'))};"
              + ("global.OrreryDemo={on:true};" if demo else "")
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
