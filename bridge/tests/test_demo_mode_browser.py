"""Demo mode in a real browser: nothing real is ever painted, and clicks,
copies and edits keep the real values (2026-09-30).

Run from bridge/: ``python -m pytest tests/test_demo_mode_browser.py``.
Skipped when no Chromium is found (set ORRERY_CHROME to point at one).

The page is the real cockpit.html, served with a mock backend: the identity
endpoint (names or a failure), a telemetry page that holds names and loads
slowly, and nothing else. The names are made up (mira, anne, mira-studio).
Each case is a finding of the review of 66887a1, reproduced first.
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
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

import pytest

HERE = Path(__file__).resolve().parent
BRIDGE = HERE.parent
sys.path.insert(0, str(BRIDGE.parent))
from tools import theme_axis_browser_test as cdp  # noqa: E402

CHROME = cdp.find_chrome()
pytestmark = pytest.mark.skipif(CHROME is None, reason="no Chromium (set ORRERY_CHROME)")

IDENTITY = {"home": "/Users/mira", "users": ["mira", "anne"], "hosts": ["mira-studio"]}
DRAFT = "Please read /Users/mira/private.txt on mira-studio"
FRAME_HTML = (b"<!doctype html><html><body><p id=raw>/Users/mira/private.txt on mira-studio</p>"
              b"<img src='/slow.png'></body></html>")


CHROME_START_SECONDS = 90


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BRIDGE), **kwargs)

    def log_message(self, *_):
        pass

    def handle(self):
        with contextlib.suppress(ConnectionError):  # the browser gave up on a slow reply
            super().handle()

    def send(self, status, body=b"", kind="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        path = urlsplit(self.path).path
        if path == "/telemetry/identity":
            mode = self.server.identity_mode
            if mode == "error":
                return self.send(503, b'{"error":"down"}')
            if mode == "hang":
                time.sleep(8)
            return self.send(200, json.dumps(IDENTITY).encode())
        if path.startswith("/network"):
            return self.send(200, FRAME_HTML, "text/html")
        if path == "/slow.png":
            time.sleep(3)
            return self.send(404, b"")
        if path.startswith("/telemetry/") or path.startswith("/api/"):
            return self.send(404, b"{}")
        return super().do_GET()


@contextlib.contextmanager
def browser(identity_mode="ok"):
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.identity_mode = identity_mode
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = cdp._free_port()
    profile = tempfile.mkdtemp(prefix="orrery-demo-cdp-")
    chrome_log = open(Path(profile) / "chrome.log", "w+")
    process = subprocess.Popen(
        [CHROME, "--headless=new", "--use-mock-keychain", "--password-store=basic", "--no-sandbox", "--disable-gpu", f"--remote-debugging-port={port}",
         "--window-size=1400,900", f"--user-data-dir={profile}", "about:blank"],
        stdout=chrome_log, stderr=subprocess.STDOUT)
    try:
        page = None
        # A deadline, not a poll count: the first Chromium start on a fresh CI
        # runner (no font or profile caches yet) took longer than 300 polls,
        # while every later start in the same run came up at once.
        started = time.monotonic()
        while time.monotonic() - started < CHROME_START_SECONDS:
            with contextlib.suppress(OSError, ValueError):
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=2))
                page = next((tab for tab in tabs if tab["type"] == "page"), None)
                if page:
                    break
            if process.poll() is not None:
                break
            time.sleep(.1)
        if page is None:
            chrome_log.seek(0)
            raise RuntimeError(f"Chromium gave no page over CDP after {time.monotonic() - started:.1f}s "
                               f"(exit {process.poll()}):\n" + chrome_log.read()[-3000:])
        client = cdp._WebSocket(page["webSocketDebuggerUrl"])
        client.call("Page.enable")
        client.call("Runtime.enable")
        client.call("Page.addScriptToEvaluateOnNewDocument",
                    source=f"localStorage.setItem('oc-prompt-draft',{json.dumps(DRAFT)});")

        def go(query):
            client.call("Page.navigate", url=f"http://127.0.0.1:{server.server_port}/cockpit.html?{query}")

        def js(expression):
            result = client.call("Runtime.evaluate", expression=expression, awaitPromise=True, returnByValue=True)
            if result.get("exceptionDetails"):
                raise AssertionError(result["exceptionDetails"])
            return result.get("result", {}).get("value")

        js.client = client  # for a screenshot when investigating
        yield go, js
    finally:
        process.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=5)
        if process.poll() is None:
            process.kill()
        server.shutdown()
        server.server_close()
        chrome_log.close()
        shutil.rmtree(profile, ignore_errors=True)


def wait(js, expression, seconds=8.0):
    deadline = time.time() + seconds
    while time.time() < deadline:
        with contextlib.suppress(AssertionError):  # the page may still be navigating
            if js(expression):
                return True
        time.sleep(.1)
    return False


# A terminal is masked where it is drawn: its buffer stays real. What counts
# is what xterm has put in the DOM rows. PANE also starts a recorder: a
# MutationObserver on the rows, created after demo mode's own, so its callback
# runs in the same microtask checkpoint right after the masking, before the
# browser can paint. Every state it records is a state that could be painted.
PANE = """(()=>{createPane('SyntheticCurie',{paneId:'demo-pane'});window.demoPane=panes.get('demo-pane');
  demoPane.host.classList.add('on');document.getElementById('stageEmpty').style.display='none';demoPane.fit.fit();
  window.painted=[];
  const rows=demoPane.host.querySelector('.xterm-rows');
  new MutationObserver(()=>painted.push([...rows.children].map(r=>r.textContent).join('\\n')))
    .observe(rows,{subtree:true,childList:true,characterData:true});
  return true;})()"""


def drawn(js):
    """The terminal's rows as drawn (trailing spaces dropped)."""
    return js("[...demoPane.host.querySelector('.xterm-rows').children].map(r=>r.textContent.replace(/\\s+$/,''))")


def buffer_rows(js):
    return js("""(()=>{const b=demoPane.term.buffer.active,out=[];
      for(let y=0;y<b.length;y++)out.push(b.getLine(y).translateToString(true));return out;})()""")


def write(js, data, pause=0.0):
    js(f"writePaneOutput(demoPane,{{data:{json.dumps(data)}}})")
    time.sleep(pause or .15)


def never_painted(js, *names):
    states = js("painted")
    leaks = [state for state in states for name in names if name.lower() in state.lower()]
    return leaks, len(states)


def copy_rows(js, first, last):
    """Copy through xterm's own selection and copy handler."""
    return js(f"""(()=>{{const t=demoPane.term;t.selectLines({first},{last});
      const data=new DataTransfer();
      t.textarea.dispatchEvent(new ClipboardEvent('copy',{{clipboardData:data,bubbles:true,cancelable:true}}));
      return data.getData('text/plain');}})()""")


def start_pane(js, cols=None):
    js(PANE)
    if cols:
        js(f"demoPane.term.resize({cols},12)")
        time.sleep(.1)


def open_demo(go, js):
    go("demo=1")
    assert wait(js, "document.documentElement.dataset.demo==='on'")


def test_terminal_names_are_masked_where_drawn_split_slow_coloured_or_prompted():
    """The first review's cases (66887a1): a colour change inside the name,
    a name split over two writes with a pause, a prompt after a colour code."""
    with browser() as (go, js):
        open_demo(go, js)
        start_pane(js)
        write(js, "ANSI: /Users/mi\x1b[31mra\x1b[0m/private.txt\r\n")
        write(js, "Late: /Users/mi", pause=.3)
        write(js, "ra/private.txt\r\n")
        write(js, "\x1b[32mmira@mira-studio\x1b[0m:~$ ")
        rows = drawn(js)
        assert rows[:3] == ["ANSI: /Users/****/private.txt", "Late: /Users/****/private.txt",
                            "****@***********:~$"]
        leaks, states = never_painted(js, "mira")
        assert states > 3 and not leaks
        # The buffer is real: that is what the cursor, copy and links use.
        assert buffer_rows(js)[0] == "ANSI: /Users/mira/private.txt"


def test_a_name_built_with_backspaces_and_colours_is_masked():
    """Second review R1: "/Users/xx", then two backspaces and "mi<red>ra"."""
    with browser() as (go, js):
        open_demo(go, js)
        start_pane(js)
        write(js, "/Users/xx", pause=.2)
        write(js, "\b\bmi\x1b[31mra\x1b[0m/x\r\n")
        assert drawn(js)[0] == "/Users/****/x"
        leaks, _ = never_painted(js, "mira")
        assert not leaks


def test_a_name_wrapped_over_two_rows_is_masked_and_copied_whole():
    """Second review R2 and R3, at 9 columns."""
    with browser() as (go, js):
        open_demo(go, js)
        start_pane(js, cols=9)
        write(js, "/Users/mir", pause=.3)
        write(js, "a/x\r\n")
        write(js, "/Users/mira/x\r\n")
        rows = drawn(js)
        assert rows[:4] == ["/Users/**", "**/x", "/Users/**", "**/x"]   # no doubled row
        leaks, _ = never_painted(js, "mira", "mir", "ra/x")
        assert not leaks
        assert copy_rows(js, 2, 3) == "/Users/mira/x"


def test_literal_stars_written_over_a_masked_name_copy_as_stars():
    """Second review R4."""
    with browser() as (go, js):
        open_demo(go, js)
        start_pane(js)
        write(js, "/Users/mira/x\r\n")
        write(js, "\x1b[1;1H\x1b[2K/Users/****/x\r\n")
        # xterm draws on an animation frame; a busy CI runner had not drawn
        # the row yet 0.15s after the write (CI run 37169738585).
        first_row = "[...demoPane.host.querySelector('.xterm-rows').children][0].textContent.replace(/\\s+$/,'')"
        assert wait(js, f"{first_row}==='/Users/****/x'"), drawn(js)[:2]
        assert copy_rows(js, 0, 0) == "/Users/****/x"


def test_copy_and_click_use_the_real_text():
    """Same-length names, typed stars and letter case all stay what they are."""
    with browser() as (go, js):
        open_demo(go, js)
        start_pane(js)
        write(js, "/Users/anne/x\r\n/Users/****/x\r\n/Users/Mira/x\r\nsee https://example.com/Users/anne/page\r\n")
        assert drawn(js)[:3] == ["/Users/****/x", "/Users/****/x", "/Users/****/x"]
        assert [copy_rows(js, y, y) for y in range(3)] == ["/Users/anne/x", "/Users/****/x", "/Users/Mira/x"]
        clicked = js("""(async()=>{window.demoClicked=[];revealLocalPath=p=>demoClicked.push(['path',p]);
          openExternalUrl=u=>demoClicked.push(['url',u]);
          for(const provider of demoPane.term._core._linkProviderService.linkProviders)
            for(const y of [1,2,3,4]){
              const links=await new Promise(r=>provider.provideLinks(y,r));
              for(const link of links||[])link.activate({preventDefault(){}},link.text);
            }
          return demoClicked;})()""")
        assert sorted(clicked) == sorted([["path", "/Users/anne/x"], ["path", "/Users/****/x"],
                                          ["path", "/Users/Mira/x"], ["url", "https://example.com/Users/anne/page"]])


def test_the_alternate_screen_and_a_resize_redraw_are_masked():
    with browser() as (go, js):
        open_demo(go, js)
        start_pane(js)
        write(js, "\x1b[?1049h\x1b[H/Users/mira/full-screen app\r\n")
        assert drawn(js)[0] == "/Users/****/full-screen app"
        write(js, "\x1b[?1049l/Users/mira/back\r\n")
        js("demoPane.term.resize(20,8)")
        time.sleep(.2)
        js("demoPane.term.resize(80,12)")
        time.sleep(.2)
        assert not [row for row in drawn(js) if "mira" in row.lower()]
        leaks, _ = never_painted(js, "mira")
        assert not leaks


def test_a_dom_copy_restores_each_node_at_its_own_place():
    """Second review R5: a typed "****" in an earlier node must stay."""
    with browser() as (go, js):
        open_demo(go, js)
        copied = js("""(async()=>{const d=document.createElement('div');
          d.innerHTML='<span>/Users/****/x </span><span>/Users/anne/x</span> and <span>/Users/anne/a</span>';
          document.body.appendChild(d);await new Promise(r=>setTimeout(r,50));
          const range=document.createRange();range.selectNodeContents(d);
          const s=getSelection();s.removeAllRanges();s.addRange(range);
          const data=new DataTransfer();
          d.dispatchEvent(new ClipboardEvent('copy',{clipboardData:data,bubbles:true,cancelable:true}));
          return [d.textContent,data.getData('text/plain')];})()""")
        assert copied == ["/Users/****/x /Users/****/x and /Users/****/a",
                          "/Users/****/x /Users/anne/x and /Users/anne/a"]


def test_fields_show_the_mask_and_keep_the_real_value():
    """P2-2: a restored draft holding a home path and the host name."""
    with browser() as (go, js):
        go("demo=1")
        assert wait(js, "document.documentElement.dataset.demo==='on'")
        time.sleep(.5)
        field = js("""(()=>{const f=document.getElementById('promptInput');const o=f.__demoOverlay;
          return {value:f.value,overlay:o?o.textContent:null,color:getComputedStyle(f).color,
                  fill:getComputedStyle(f).webkitTextFillColor};})()""")
        assert field["value"] == DRAFT                       # sending uses the real text
        assert field["overlay"].strip() == "Please read /Users/****/private.txt on ***********"
        assert field["color"] in ("rgba(0, 0, 0, 0)", "transparent") and field["fill"] in ("rgba(0, 0, 0, 0)", "transparent")
        # A value set by code (history recall) is masked at once too.
        later = js("""(()=>{const f=document.getElementById('promptInput');f.value='cd /home/anne';
          return f.__demoOverlay?f.__demoOverlay.textContent:null;})()""")
        assert later.strip() == "cd /home/****"
        # And a field without a name is left alone.
        plain = js("""(()=>{const f=document.getElementById('promptInput');f.value='hello';
          return [f.__demoOverlay?1:0,getComputedStyle(f).color];})()""")
        assert plain[0] == 0 and plain[1] not in ("rgba(0, 0, 0, 0)", "transparent")


def test_the_telemetry_frame_is_never_shown_before_it_is_masked():
    """P2-1: the frame's document was painted before its load event."""
    with browser() as (go, js):
        go("demo=1")
        assert wait(js, "document.documentElement.dataset.demo==='on'")
        js("openNetwork({focus:''})")
        seen = []
        deadline = time.time() + 4.5
        while time.time() < deadline:
            seen.append(js("""(()=>{const f=networkFrame;let text='';try{text=f.contentDocument.body?f.contentDocument.body.innerText:''}catch(_){}
              return {visible:getComputedStyle(f).visibility!=='hidden',raw:/mira/i.test(text),ready:f.contentDocument&&f.contentDocument.readyState};})()"""))
            time.sleep(.05)
        assert not [s for s in seen if s["visible"] and s["raw"]], seen
        assert any(s["ready"] == "loading" or s["ready"] == "interactive" for s in seen)  # the window existed
        final = seen[-1]
        assert final["visible"] and not final["raw"]
        assert js("networkFrame.contentDocument.getElementById('raw').textContent") == "/Users/****/private.txt on ***********"


@pytest.mark.parametrize("mode, reason", [("error", "503"), ("hang", "no answer in 5 seconds")])
def test_without_the_names_the_page_stays_hidden_and_says_why(mode, reason):
    """P2-6: an identity failure used to show everything unmasked."""
    with browser(identity_mode=mode) as (go, js):
        go("demo=1")
        assert wait(js, "document.documentElement.dataset.demo==='failed'", seconds=9)
        state = js("""(()=>{const probe=document.createElement('div');probe.textContent='/Users/mira/x';document.body.appendChild(probe);
          const panel=document.querySelector('.demo-status');
          return {known:OrreryDemo.known,probe:getComputedStyle(probe).visibility,
                  panel:panel?getComputedStyle(panel).visibility:null,text:panel?panel.innerText:'',
                  connected:typeof socket!=='undefined'&&socket!==null};})()""")
        assert state["known"] is False
        assert state["probe"] == "hidden"                    # nothing of the page is painted
        assert state["panel"] == "visible" and reason in state["text"] and "Retry" in state["text"]
        assert state["connected"] is False                  # no terminal output either


def test_without_demo_nothing_changes():
    with browser() as (go, js):
        go("demo=0")
        assert wait(js, "typeof panes!=='undefined'")
        time.sleep(.5)
        start_pane(js)
        write(js, "/Users/mira/x mira@mira-studio\r\n")
        assert drawn(js)[0] == "/Users/mira/x mira@mira-studio"
        assert js("document.getElementById('promptInput').value") == DRAFT
        assert js("document.documentElement.hasAttribute('data-demo')") is False


# ---------------------------------------------------------------- added words

WORD_CHECK = """(async()=>{
  const d=document.createElement('div');d.id='word-check';d.textContent='Ask Kobo about kobold';document.body.appendChild(d);
  await new Promise(r=>setTimeout(r,50));
  const range=document.createRange();range.selectNodeContents(d);
  const s=getSelection();s.removeAllRanges();s.addRange(range);
  const data=new DataTransfer();
  d.dispatchEvent(new ClipboardEvent('copy',{clipboardData:data,bubbles:true,cancelable:true}));
  return [d.textContent,data.getData('text/plain')];})()"""


def test_saved_words_are_masked_on_screen_and_copied_as_they_are():
    with browser() as (go, js):
        go("demo=0")
        assert wait(js, "typeof OrreryDemo!=='undefined'")
        js("OrreryDemo.setWords(['Kobo'],{reload:false})")
        go("demo=1")
        assert wait(js, "document.documentElement.dataset.demo==='on'")
        assert js(WORD_CHECK) == ["Ask **** about kobold", "Ask Kobo about kobold"]
        start_pane(js)
        write(js, "mail from KOBO: hi\r\n")
        assert drawn(js)[0] == "mail from ****: hi"
        assert copy_rows(js, 0, 0) == "mail from KOBO: hi"
        # The Settings field holds the real words and shows them masked.
        field = js("""(()=>{const f=document.getElementById('demoMaskWords');
          return [f.value,f.__demoOverlay?f.__demoOverlay.textContent:null];})()""")
        assert field == ["Kobo", "****"]


def test_words_in_the_url_count_for_that_page_and_its_pane_windows():
    with browser() as (go, js):
        go("demo=1&mask=Kobo,%E3%83%9F%E3%83%A9%E3%83%8E")
        assert wait(js, "document.documentElement.dataset.demo==='on'")
        shown = js("""(async()=>{const d=document.createElement('div');d.textContent='Kobo and ミラノさん';
          document.body.appendChild(d);await new Promise(r=>setTimeout(r,50));return d.textContent;})()""")
        assert shown == "**** and ＊＊＊さん"
        assert "mask=Kobo" in js("paneWindowUrl(location.href,'s1')")


def test_negative_words_do_nothing_without_demo_mode():
    with browser() as (go, js):
        go("demo=0&mask=Kobo")
        assert wait(js, "typeof panes!=='undefined'")
        time.sleep(.3)
        assert js(WORD_CHECK) == ["Ask Kobo about kobold", ""]


@pytest.mark.parametrize("scroll, shown", [
    (1, ["****/x", "TAIL"]),          # "/Users/" is above the view
    (0, ["/Users/", "****/x"]),       # "/x" is kept, "TAIL" below the view
])
def test_a_wrapped_name_whose_other_rows_are_out_of_view_is_masked(scroll, shown):
    """Review of 00b220b: with the "/Users/" row scrolled out of view, the
    drawn top row showed the name, since only drawn rows were matched."""
    with browser() as (go, js):
        open_demo(go, js)
        js(PANE)
        js("demoPane.term.resize(7,2)")
        time.sleep(.1)
        write(js, "/Users/mira/x\r\nTAIL")
        js(f"demoPane.term.scrollToLine({scroll})")
        time.sleep(.2)
        assert drawn(js) == shown
        leaks, _ = never_painted(js, "mira", "ira/")
        assert not leaks
        assert copy_rows(js, 0, 1) == "/Users/mira/x"
