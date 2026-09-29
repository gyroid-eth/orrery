"""The cockpit follows the backend's host: labels, shortcuts and paste (2026-09-28).

On WSL the page is shown in a Windows browser. The three file routes of the
composer paste (a file item, an image item, a file:// uri-list) all depend on
the macOS pasteboard reader, and before this change the image route sent ^V
and toasted success even when nothing could be read. These run the real
functions from cockpit.html under node with the host swapped, and check that
WSL never reports a paste it did not make while the Mac keeps every route.
Since 2026-09-29 a WSL backend that can run powershell.exe reads the Windows
clipboard itself (file_paste: true), and only then do the WSL routes proceed.

Run from bridge/: ``python -m pytest tests/test_cockpit_host.py``.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = Path(os.environ.get("ORRERY_BRIDGE_SOURCES", ROOT))
COCKPIT = SOURCES / "cockpit.html"

BLOCKS = (
    r"/\* ── host: Mac, WSL or plain Linux.*?(?=/\* COCKPIT_PURE_LOGIC_END \*/)",
    r"function quotePath\(path\)\{.*?\n\}\n",
    r"function handleComposerPaste\(e\)\{.*?\n\}\n",
)

HARNESS = r"""
const toasts=[],sent=[],reads=[];let drafts=0;
function showToast(message,isError=false){toasts.push({message,isError});}
function send(msg){sent.push(msg);}
function saveDraft(){drafts++;}
let clipboardAnswer={files:[]};
function readClipboardFiles(){reads.push(1);return Promise.resolve(clipboardAnswer);}
const panes=new Map([['%1',{session:'orrery-A'}]]);let activeId='%1';
const promptInput={value:'',selectionStart:0,selectionEnd:0,
  setSelectionRange(){},focus(){}};
let hostPlatform;
function pasteEvent({items=[],plain='',uris=''}={}){
  const ev={prevented:false,preventDefault(){this.prevented=true;},
    clipboardData:{items,getData:t=>t==='text/plain'?plain:t==='text/uri-list'?uris:''}};
  return ev;
}
const FILE={kind:'file',type:'application/pdf'};
const IMAGE={kind:'file',type:'image/png'};
async function paste(host,spec,answer={files:[]}){
  hostPlatform=normalizeHostPlatform(host);clipboardAnswer=answer;
  toasts.length=0;sent.length=0;reads.length=0;promptInput.value='';
  const ev=pasteEvent(spec);handleComposerPaste(ev);
  await new Promise(r=>setTimeout(r,0));await new Promise(r=>setTimeout(r,0));
  return {prevented:ev.prevented,toasts:[...toasts],sent:[...sent],reads:reads.length,
    value:promptInput.value};
}
const MAC={host:'mac',terminal:{kind:'ghostty',label:'Ghostty',available:true},file_paste:true};
const WSL={host:'wsl',terminal:{kind:'wt',label:'Windows Terminal',available:true},file_paste:false};
const WSL_READER={...WSL,file_paste:true};
const LINUX={host:'linux',terminal:{kind:'ghostty',label:'Ghostty',available:true},file_paste:false};
run().then(r=>console.log(JSON.stringify(r)));
"""


def _run(body: str):
    html = COCKPIT.read_text(encoding="utf-8")
    parts = []
    for pattern in BLOCKS:
        match = re.search(pattern, html, re.DOTALL)
        assert match, f"missing block in cockpit.html: {pattern}"
        parts.append(match.group(0))
    script = "\n".join([f"async function run(){{\n{body}\n}}", *parts, HARNESS])
    done = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


# --- paste ---------------------------------------------------------------------


def test_wsl_without_a_reader_does_not_report_any_of_the_three_file_routes_as_done():
    r = _run("""return {
      file:await paste(WSL,{items:[FILE]},{files:['/tmp/x.pdf']}),
      image:await paste(WSL,{items:[IMAGE]}),
      imageAfterReaderError:await paste(WSL,{items:[IMAGE]},{files:[],error:'clipboard_unsupported'}),
      uri:await paste(WSL,{uris:'file:///C:/Users/u/x.pdf'}),
    };""")
    for route, out in r.items():
        assert out["prevented"], route
        assert out["sent"] == [], route          # no ^V to the TUI
        assert out["reads"] == 0, route          # no pasteboard reader asked
        assert out["value"] == "", route         # nothing inserted
        assert len(out["toasts"]) == 1, route
        toast = out["toasts"][0]
        assert toast["isError"] is True, route
        assert "not available on Windows" in toast["message"], route


def test_an_undetermined_host_holds_the_three_file_routes():
    """Before /telemetry/platform answers, or when it failed, nothing is sent
    and nothing is reported as pasted (review of PR #2: the image route used
    to fall back to ^V and a success toast on a WSL backend)."""
    r = _run("""return {
      file:await paste(null,{items:[FILE]},{files:['/tmp/x.pdf']}),
      image:await paste(null,{items:[IMAGE]},{files:[],error:'clipboard_unsupported'}),
      imageBadAnswer:await paste({host:'windows'},{items:[IMAGE]}),
      uri:await paste(undefined,{uris:'file:///C:/Users/u/x.pdf'}),
      text:await paste(null,{plain:'hello'}),
    };""")
    for route in ("file", "image", "imageBadAnswer", "uri"):
        out = r[route]
        assert out["prevented"], route
        assert out["sent"] == [] and out["reads"] == 0 and out["value"] == "", route
        assert [t["isError"] for t in out["toasts"]] == [True], route
        assert "held" in out["toasts"][0]["message"], route
    assert r["text"]["prevented"] is False and r["text"]["toasts"] == []


def test_a_backend_without_a_reader_outranks_the_image_fallback():
    """Even on a host that allows the reader, clipboard_unsupported stops ^V."""
    r = _run("""return {
      mac:await paste(MAC,{items:[IMAGE]},{files:[],error:'clipboard_unsupported'}),
      prefixed:await paste(MAC,{items:[IMAGE]},{files:[],error:'app reader: x; clipboard_unsupported'}),
      linux:await paste(LINUX,{items:[IMAGE]},{files:[],error:'clipboard_unsupported'}),
    };""")
    for route, out in r.items():
        assert out["sent"] == [], route
        assert [t["isError"] for t in out["toasts"]] == [True], route
        assert "not available" in out["toasts"][0]["message"], route


def test_wsl_with_the_powershell_reader_pastes_windows_files_as_wsl_paths():
    """2026-09-29: the backend reads the Windows clipboard, so an Explorer
    copy lands as /mnt/c/... paths and a screenshot as the PNG it saved."""
    r = _run("""return {
      file:await paste(WSL_READER,{items:[FILE]},{files:['/mnt/c/Users/u/a b.pdf']}),
      image:await paste(WSL_READER,{items:[IMAGE]},
        {files:['/tmp/orrery-clipboard-1000/clipboard-1.png'],image:true}),
      uri:await paste(WSL_READER,{uris:'file:///C:/Users/u/x.pdf'},{files:['/mnt/c/Users/u/x.pdf']}),
    };""")
    assert r["file"]["value"] == "'/mnt/c/Users/u/a b.pdf'" and r["file"]["reads"] == 1
    assert r["image"]["value"] == "/tmp/orrery-clipboard-1000/clipboard-1.png"
    assert r["image"]["toasts"] == [{"message": "image saved as PNG → path → composer",
                                     "isError": False}]
    # the Windows file:// URI is never decoded into /C:/...; the backend answers
    assert r["uri"]["value"] == "/mnt/c/Users/u/x.pdf" and r["uri"]["reads"] == 1
    for route, out in r.items():
        assert out["prevented"] and out["sent"] == [], route


def test_wsl_says_which_files_did_not_become_wsl_paths():
    r = _run("""return await paste(WSL_READER,{items:[FILE]},
      {files:['/mnt/c/a.txt'],skipped:['\\\\\\\\server\\\\x.pdf']});""")
    assert r["value"] == "/mnt/c/a.txt"
    assert r["toasts"][-1]["isError"] is True
    assert r["toasts"][-1]["message"].startswith("1 of 2 files not pasted")
    assert "server" in r["toasts"][-1]["message"]


def test_wsl_never_falls_back_to_ctrl_v():
    """The TUI inside WSL cannot read the Windows clipboard: ^V would be
    reported as an image paste that read nothing."""
    r = _run("""return {
      empty:await paste(WSL_READER,{items:[IMAGE]},{files:[]}),
      noSession:await paste(WSL_READER,{items:[IMAGE]},{files:[],error:'clipboard_no_session'}),
      file:await paste(WSL_READER,{items:[FILE]},{files:[]}),
    };""")
    for route, out in r.items():
        assert out["sent"] == [] and out["value"] == "", route
        assert len(out["toasts"]) == 1, route
    assert r["empty"]["toasts"][0]["isError"] is True
    assert "Windows clipboard" in r["empty"]["toasts"][0]["message"]
    assert r["noSession"]["toasts"][0] == {
        "message": "clipboard reader failed (clipboard_no_session)", "isError": True}
    assert r["file"]["toasts"][0]["message"] == "nothing on the clipboard the composer can use"


def test_wsl_keeps_plain_text_paste():
    for host in ("WSL", "WSL_READER"):
        r = _run(f"return await paste({host},{{plain:'hello'}});")
        assert r == {"prevented": False, "toasts": [], "sent": [], "reads": 0, "value": ""}


def test_the_mac_keeps_every_route():
    r = _run("""return {
      file:await paste(MAC,{items:[FILE]},{files:['/tmp/a b.pdf']}),
      image:await paste(MAC,{items:[IMAGE]}),
      uri:await paste(MAC,{uris:'file:///Users/u/x.pdf'}),
      text:await paste(MAC,{plain:'hello'}),
    };""")
    assert r["file"]["value"] == "'/tmp/a b.pdf'"
    assert r["file"]["toasts"] == [{"message": "path → composer", "isError": False}]
    assert r["image"]["sent"] == [{"type": "input", "paneId": "%1", "data": "\x16"}]
    assert r["image"]["toasts"][0]["message"].startswith("image → orrery-A")
    assert r["uri"]["value"] == "/Users/u/x.pdf" and r["uri"]["reads"] == 0
    assert r["text"]["prevented"] is False


def test_plain_linux_paste_is_unchanged():
    r = _run("return await paste(LINUX,{items:[IMAGE]});")
    assert r["reads"] == 1
    assert r["sent"] == [{"type": "input", "paneId": "%1", "data": "\x16"}]


def test_the_handler_is_the_one_on_the_composer():
    html = COCKPIT.read_text(encoding="utf-8")
    assert "promptInput.addEventListener('paste',handleComposerPaste);" in html


# --- shortcuts -----------------------------------------------------------------


def test_shortcuts_follow_the_host():
    r = _run("""
      const ev=(key,mods={})=>({key,metaKey:false,ctrlKey:false,altKey:false,shiftKey:false,...mods});
      const h=normalizeHostPlatform;
      return {
        macPalette:isPaletteShortcut(ev('k',{metaKey:true}),h(MAC)),
        macPaletteAlt:isPaletteShortcut(ev('k',{altKey:true}),h(MAC)),
        macJump:sessionJumpNumber(ev('3',{metaKey:true}),h(MAC)),
        linuxPalette:isPaletteShortcut(ev('k',{metaKey:true}),h(LINUX)),
        wslPalette:isPaletteShortcut(ev('k',{altKey:true}),h(WSL)),
        wslPaletteUpper:isPaletteShortcut(ev('K',{altKey:true}),h(WSL)),
        wslPaletteCtrl:isPaletteShortcut(ev('k',{ctrlKey:true}),h(WSL)),
        wslPaletteMeta:isPaletteShortcut(ev('k',{metaKey:true}),h(WSL)),
        wslAltGr:isPaletteShortcut(ev('k',{altKey:true,ctrlKey:true}),h(WSL)),
        wslJump:sessionJumpNumber(ev('3',{altKey:true}),h(WSL)),
        wslJumpCtrl:sessionJumpNumber(ev('3',{ctrlKey:true}),h(WSL)),
        wslJumpZero:sessionJumpNumber(ev('0',{altKey:true}),h(WSL)),
        wslYield:terminalYieldsHostShortcut(ev('2',{altKey:true}),h(WSL)),
        wslYieldOther:terminalYieldsHostShortcut(ev('b',{altKey:true}),h(WSL)),
        macYield:terminalYieldsHostShortcut(ev('k',{metaKey:true}),h(MAC)),
        before:normalizeHostPlatform(null).host,
      };""")
    assert r == {
        "macPalette": True, "macPaletteAlt": False, "macJump": 3,
        "linuxPalette": True,
        "wslPalette": True, "wslPaletteUpper": True, "wslPaletteCtrl": False,
        "wslPaletteMeta": False, "wslAltGr": False,
        "wslJump": 3, "wslJumpCtrl": 0, "wslJumpZero": 0,
        "wslYield": True, "wslYieldOther": False, "macYield": False,
        "before": "unknown",
    }


def test_labels_follow_the_host():
    r = _run("""const h=normalizeHostPlatform;return {
      mac:[paletteShortcutLabel(h(MAC)),splitClickLabel(h(MAC)),terminalActionText(h(MAC)),terminalSpawnLabel(h(MAC))],
      linux:[paletteShortcutLabel(h(LINUX)),terminalActionText(h(LINUX)),terminalSpawnLabel(h(LINUX))],
      wsl:[paletteShortcutLabel(h(WSL)),splitClickLabel(h(WSL)),terminalActionText(h(WSL)),terminalSpawnLabel(h(WSL))],
    };""")
    assert r["mac"] == ["⌘K", "⌘+click", "GHOSTTY", "Open a Ghostty window"]
    assert r["linux"] == ["⌘K", "GHOSTTY", "Open a Ghostty window"]
    assert r["wsl"] == ["Alt+K", "Ctrl+click", "WIN TERMINAL", "Open a Windows Terminal tab"]


def test_the_shortcuts_are_wired_to_the_page_and_the_terminal():
    html = COCKPIT.read_text(encoding="utf-8")
    assert "if(isPaletteShortcut(event,hostPlatform)){" in html
    assert "sessionJumpNumber(event,hostPlatform)){" in html
    assert "if(terminalYieldsHostShortcut(event,hostPlatform))return false;" in html
    assert "fetch('/telemetry/platform'" in html
    # the old Cmd-only checks are gone, so nothing bypasses the host
    assert "event.metaKey&&!event.altKey&&!event.shiftKey&&key==='k'" not in html
    assert "/^[1-9]$/.test(event.key)){" not in html
