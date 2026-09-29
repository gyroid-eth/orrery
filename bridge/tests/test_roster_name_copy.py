"""Copy an agent's name from the roster (2026-09-28).

The copied text must be the name itself — what Mail and spawn take — and the
copy button must not also trigger the tile's jump. These run the real
functions from cockpit.html under node.

Run from bridge/: ``python -m pytest tests/test_roster_name_copy.py``.
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
    r"const NAME_COPY_TIMEOUT_MS=.*?\n",
    r"function copyAgentName\(name,clipboard,timeoutMs=NAME_COPY_TIMEOUT_MS\)\{.*?\n\}\n",
    r"function handleNameCopy\(name,event\)\{.*?\n\}\n",
)

HARNESS = r"""
const toasts=[];function showToast(message,isError=false){toasts.push({message,isError});}
const written=[];
// node ships a read-only navigator of its own; replace it for the page code
Object.defineProperty(globalThis,'navigator',{configurable:true,writable:true,
  value:{clipboard:{writeText:t=>{written.push(t);return Promise.resolve();}}}});
function event(){return {prevented:false,stopped:false,
  preventDefault(){this.prevented=true;},stopPropagation(){this.stopped=true;}};}
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


def test_the_copied_text_is_the_bare_name():
    r = _run("""
      const ev=event();const ok=await handleNameCopy('KindMendel',ev);
      return {ok,written,toasts,stopped:ev.stopped,prevented:ev.prevented};""")
    assert r["written"] == ["KindMendel"]
    assert r["ok"] is True
    assert r["toasts"] == [{"message": "COPIED · KindMendel", "isError": False}]
    # the tile underneath must not see this click (no jump)
    assert r["stopped"] is True and r["prevented"] is True


def test_a_missing_or_refusing_clipboard_is_an_error_not_a_copy():
    r = _run("""
      const out={};
      navigator={};out.none=await handleNameCopy('A',event());
      navigator={clipboard:{writeText:()=>Promise.reject(new Error('Document is not focused'))}};
      out.refused=await handleNameCopy('A',event());
      out.toasts=toasts;return out;""")
    assert r["none"] is False and r["refused"] is False
    assert [t["isError"] for t in r["toasts"]] == [True, True]
    assert "clipboard unavailable" in r["toasts"][0]["message"]
    assert "Document is not focused" in r["toasts"][1]["message"]


def test_a_clipboard_that_never_answers_is_reported():
    r = _run("""
      navigator={clipboard:{writeText:()=>new Promise(()=>{})}};
      const failed=await copyAgentName('A',navigator.clipboard,20).then(()=>'copied',e=>e.message);
      return {failed};""")
    assert r["failed"] == "the clipboard did not answer"


def test_copy_takes_the_record_name_not_the_painted_text():
    """The tile's name comes from the agent record, not from DOM text that
    other painters could decorate."""
    html = COCKPIT.read_text(encoding="utf-8")
    assert "copyButton.onclick=event=>handleNameCopy(a.name,event);" in html
    # the tile's own click still jumps
    assert "el.onclick=event=>handleRosterTileClick(a.name,event);" in html
