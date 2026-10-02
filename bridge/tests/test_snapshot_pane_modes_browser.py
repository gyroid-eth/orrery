"""The replay, applied by the xterm the cockpit uses (2026-10-02).

What counts is what a real xterm makes of the replay: the mouse mode it ends
in, what a wheel turns into, and that nothing else changes. Each review case
of the earlier, larger version (live output before the replay, a line printed
after the capture, bracketed paste) is compared here against the same replay
without the added modes — the text the cockpit sent before this change.

Needs Chromium (ORRERY_CHROME) and the network for xterm, like the cockpit.
"""
from __future__ import annotations

import contextlib
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent))
from tools import theme_axis_browser_test as cdp  # noqa: E402
from test_snapshot_pane_modes import (  # noqa: E402
    CLASSIC_WHEEL,
    FULLSCREEN,
    _replay,
    _state,
)

CHROME = cdp.find_chrome()
pytestmark = pytest.mark.skipif(CHROME is None, reason="no Chromium (set ORRERY_CHROME)")

PAGE = b"""<!doctype html><meta charset=utf-8>
<script src="https://cdn.jsdelivr.net/npm/@xterm/xterm@5.5.0/lib/xterm.js"></script>
<body><script>
function dump(t){
  const b=t.buffer,rows=buf=>Array.from({length:buf.length},(_,i)=>buf.getLine(i).translateToString(true));
  return {mode:t.modes.mouseTrackingMode,active:b.active.type,paste:t.modes.bracketedPasteMode,
          normal:rows(b.normal),alternate:rows(b.alternate),cursor:[b.active.cursorX,b.active.cursorY]};
}
async function apply(cols,rows,writes){
  const host=document.createElement('div');document.body.appendChild(host);
  const t=new Terminal({cols,rows});t.open(host);
  const data=[],binary=[];t.onData(x=>data.push(x));t.onBinary(x=>binary.push(x));
  for(const w of writes)await new Promise(r=>t.write(w,r));
  await new Promise(r=>requestAnimationFrame(r));
  return {t,host,data,binary};
}
async function wheelAt(term,col){
  const screen=term.host.querySelector('.xterm-screen'),rect=screen.getBoundingClientRect();
  const cell=rect.width/term.t.cols;
  screen.dispatchEvent(new WheelEvent('wheel',{bubbles:true,cancelable:true,
    clientX:rect.left+cell*(col-0.5),clientY:rect.top+5,deltaY:-120}));
  await new Promise(r=>setTimeout(r,100));
}
</script>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(PAGE)))
        self.end_headers()
        self.wfile.write(PAGE)


@pytest.fixture(scope="module")
def js():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = cdp._free_port()
    profile = tempfile.mkdtemp(prefix="orrery-modes-cdp-")
    process = subprocess.Popen(
        [CHROME, "--headless=new", "--no-sandbox", "--disable-gpu",
         f"--remote-debugging-port={port}", "--window-size=1400,900",
         f"--user-data-dir={profile}", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        tabs = None
        for _ in range(100):
            with contextlib.suppress(OSError):
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
                break
            time.sleep(.1)
        page = next(tab for tab in tabs if tab["type"] == "page")
        client = cdp._WebSocket(page["webSocketDebuggerUrl"])
        client.call("Page.enable")
        client.call("Runtime.enable")
        client.call("Page.navigate", url=f"http://127.0.0.1:{server.server_port}/")

        def evaluate(expression):
            result = client.call("Runtime.evaluate", expression=expression,
                                 awaitPromise=True, returnByValue=True)
            if result.get("exceptionDetails"):
                raise AssertionError(result["exceptionDetails"])
            return result.get("result", {}).get("value")

        deadline = time.time() + 15
        while time.time() < deadline:
            with contextlib.suppress(AssertionError):
                if evaluate("typeof Terminal==='function'"):
                    break
            time.sleep(.1)
        else:
            pytest.skip("xterm did not load (offline?)")
        yield evaluate
    finally:
        process.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=5)
        if process.poll() is None:
            process.kill()
        server.shutdown()
        server.server_close()
        shutil.rmtree(profile, ignore_errors=True)


MODES = "\x1b[?1003h\x1b[?1006h"
SCREEN = ["transcript", "", "> "]


def _dumps(js, *writes_list, cols=20):
    """dump() after each list of writes, each on its own fresh xterm."""
    return js(f"""(async()=>{{
      const out=[];
      for(const writes of {json.dumps(list(writes_list))})out.push(dump((await apply({cols},3,writes)).t));
      return out;
    }})()""")


def test_a_later_viewer_ends_in_mouse_mode_and_the_wheel_reaches_the_app(js):
    replay = _replay(SCREEN, _state((2, 2), **FULLSCREEN))
    result = js(f"""(async()=>{{
      const x=await apply(20,3,[{json.dumps(replay)}]);
      await wheelAt(x,5);
      return {{state:dump(x.t),data:x.data}};
    }})()""")
    assert result["state"]["mode"] == "any"
    assert result["data"] == ["\x1b[<64;5;1M"]


def test_a_blank_tui_takes_the_wheel_once_it_draws(js):
    replay = _replay(["", "", ""], _state((0, 0), **FULLSCREEN))
    result = js(f"""(async()=>{{
      const x=await apply(20,3,[{json.dumps(replay)}]);
      await new Promise(r=>x.t.write('drawn later',r));
      await wheelAt(x,5);
      return x.data;
    }})()""")
    assert result == ["\x1b[<64;5;1M"]


def test_a_classic_wheel_report_leaves_as_bytes(js):
    replay = _replay(["classic", "", ""], _state((0, 0), mouse_standard_flag="1"))
    result = js(f"""(async()=>{{
      const x=await apply(200,3,[{json.dumps(replay)}]);
      await wheelAt(x,193);
      return {{mode:x.t.modes.mouseTrackingMode,data:x.data,binary:x.binary}};
    }})()""")
    assert result["mode"] == "vt200"
    assert result["data"] == []
    assert result["binary"] == [CLASSIC_WHEEL]


@pytest.mark.parametrize(
    "live",
    [
        # Round 1: live output on the alternate screen ahead of the replay.
        "\x1b[?1049h\x1b[?1003h\x1b[?1006hLIVE OUTPUT LIVE\r\nmore\r\n",
        # Round 2: bracketed paste turned on by live output ahead of the replay.
        "\x1b[?2004h",
        # Round 2/3: a line printed once after the capture, delivered before it.
        "COMMAND_FINISHED\r\n$ ",
    ],
    ids=["alternate-first", "paste-mode-first", "line-after-capture"],
)
def test_the_buffers_are_what_the_replay_without_modes_leaves(js, live):
    """Against the text the cockpit sent before: same buffers, cursor and
    paste mode in every order; the mouse mode is the only difference."""
    replay = _replay(SCREEN, _state((2, 2), **FULLSCREEN))
    before = replay.replace(MODES, "")
    assert before != replay
    for writes in ([live, replay], [replay, live]):
        old_writes = [before if w is replay else w for w in writes]
        new, old = _dumps(js, writes, old_writes)
        assert new["mode"] == "any"
        new.pop("mode"), old.pop("mode")
        assert new == old


def test_paste_stays_bracketed_after_the_replay(js):
    replay = _replay(["$ ", "", ""], _state((2, 0)))
    result = js(f"""(async()=>{{
      const x=await apply(20,3,['\\x1b[?2004h',{json.dumps(replay)}]);
      x.t.paste('first\\nsecond');
      return x.data;
    }})()""")
    assert result == ["\x1b[200~first\rsecond\x1b[201~"]


def test_a_plain_shell_is_untouched(js):
    replay = _replay(["$ ls", "a b", "$ "], _state((2, 2)), history=["older"])
    (state,) = _dumps(js, [replay])
    assert state["mode"] == "none"
    assert state["active"] == "normal"
    assert state["normal"] == ["older", "$ ls", "a b", "$ "]
