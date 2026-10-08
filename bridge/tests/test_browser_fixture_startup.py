"""CDP cold-start and failure boundaries, without launching Chromium."""
import io
import json
from types import SimpleNamespace

import pytest

import test_snapshot_pane_modes_browser as browser


def clock(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(browser.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(browser.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))
    return now


def test_first_start_can_take_over_ten_seconds_before_a_page_is_ready(monkeypatch):
    now = clock(monkeypatch)
    page = {"type": "page", "webSocketDebuggerUrl": "ws://fixture/page"}

    def reply(url, timeout):
        assert url == "http://127.0.0.1:1234/json" and timeout == 2
        if now[0] < 12:
            raise OSError("starting")
        tabs = [] if now[0] < 13 else [page]
        return io.StringIO(json.dumps(tabs))

    monkeypatch.setattr(browser.urllib.request, "urlopen", reply)
    assert browser._wait_for_page(SimpleNamespace(poll=lambda: None), 1234, io.StringIO()) == page
    assert 13 <= now[0] < 14


def test_exited_chromium_reports_stderr_without_waiting_the_deadline(monkeypatch):
    now = clock(monkeypatch)
    with pytest.raises(RuntimeError, match=r"exit 17.*\nfixture startup failure"):
        browser._wait_for_page(SimpleNamespace(poll=lambda: 17), 1234,
                               io.StringIO("fixture startup failure"))
    assert now[0] == 0


def test_running_chromium_without_a_debuggable_page_has_a_bounded_failure(monkeypatch):
    now = clock(monkeypatch)
    monkeypatch.setattr(browser.urllib.request, "urlopen",
                        lambda *args, **kwargs: io.StringIO('[{"type":"page"}]'))
    with pytest.raises(RuntimeError, match=r"no page over CDP.*exit None.*\nfixture stderr"):
        browser._wait_for_page(SimpleNamespace(poll=lambda: None), 1234,
                               io.StringIO("fixture stderr"))
    assert 90 <= now[0] < 91
