# ORRERY bridge E2E QA

`e2e_bridge.py` owns its test lifecycle: it creates guarded tmux sessions,
starts the bridge on `127.0.0.1:8802`, exercises HTTP and WebSocket behavior,
then stops the subprocess and removes only the sessions it created.
Every tmux command, interactive client, and backend subprocess is pinned to a
per-run `tmux -L orrery-e2e-*` socket. The always-on recorder therefore cannot
discover or attach to agent and user sessions on the default tmux server.

## Setup and run

From `bridge/`:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt

python -m pytest -v tests/e2e_bridge.py
# The same suite also runs without pytest:
python tests/e2e_bridge.py -v
```

While `orrery_backend.py` is still being implemented, the v1 plumbing check
runs and the v2 contract cases are reported as skipped. After the unified
backend lands, an integration run can enable the already-written v2 cases:

```sh
ORRERY_E2E_V2=1 python -m pytest -v tests/e2e_bridge.py
```

The two spawn cases (`test_110`, `test_118`) are skipped unless the run opts
in *and* the backend's dashboard is a stand-in. `POST /telemetry/spawn` is
proxied to the dashboard, which has no `dry_run`: on 2026-09-28 a "dry-run"
probe against the real `127.0.0.1:8770` launched real agents. Never run them
against the real dashboard:

```sh
ORRERY_E2E_V2=1 ORRERY_E2E_ALLOW_SPAWN=1 \
  ORRERY_DASHBOARD_URL=http://127.0.0.1:<fake-dashboard-port> \
  python -m pytest -v tests/e2e_bridge.py
```

The v2 run includes the Cycle 8 stream-integrity case. It attaches only to a
random `orrery-qa-stream-*` session, replays every WebSocket `output` event
into a pane-sized `pyte.HistoryScreen`, and compares it row-by-row with
`tmux capture-pane` after CJK bursts and TUI-style redraws. It runs five
rounds by default; increase the stress count when diagnosing:

```sh
ORRERY_E2E_V2=1 ORRERY_STREAM_ROUNDS=20 \
  python -m pytest -v tests/e2e_bridge.py
```

On a mismatch, the assertion reports a temporary `orrery-stream-diff-*`
directory containing the pyte screen, tmux capture, unified diff, and raw
WebSocket event JSONL.

The Cycle 9 history-at-attach case deliberately waits 31 seconds after client
A disconnects. This crosses the old 30-second detach linger boundary before
client B attaches, and verifies that the same always-on recorder process and
its scrolled-off history both survive.

The Cycle 10 persistence cases inject a fresh `/private/tmp/orrery-e2e-history-*`
directory through `ORRERY_HISTORY_DIR`; they never inspect or write the live
`~/.orrery/history/` store. Each case scrolls a unique marker off the current
tmux screen, gracefully stops backend A, validates the persisted pane JSON,
then starts backend B. One case requires the marker in the attach snapshot;
the other restarts the isolated tmux server with the same session name and
pane ID but a newer `#{session_created}`, and requires the stale marker to be
absent.

## Safety rules

- Never point this suite at an existing agent or user tmux session.
- The harness uses a random, per-process tmux socket rather than the default
  server; Cycle 9's unfiltered recorder roster sees only harness-owned sessions.
- The harness creates `orrery-qa-<random>` sessions and one
  `qa-guard-<random>` session. Every session is created with
  `tmux new-session -d -s <name> -e CLAUDECODE=1`.
- The non-`orrery-` guard test uses only its own `qa-guard-<random>` session.
  It never sends `split`, `close`, input, or any other operation to a real
  agent session.
- Cleanup targets exact random names in `try`/`finally`-equivalent unittest
  class teardown. It never kills the tmux server or uses a wildcard target.
- Port `8802` is QA-only. If it is occupied, the suite fails without touching
  the listener.
- The dashboard on `127.0.0.1:8770` is accessed only indirectly through the
  backend proxy, and by default only with GET. The two spawn cases are
  skipped unless `ORRERY_E2E_ALLOW_SPAWN=1` and `ORRERY_DASHBOARD_URL` points
  at a fake dashboard (see above); a payload that "should" be rejected or is
  marked `dry_run` is no protection against the real one.
- Every backend the suite starts gets a throwaway `ORRERY_HISTORY_DIR` and
  `ORRERY_PREFS_PATH` (`ManagedServer`), and refuses to start if either points
  into the real `~/.orrery`. The test backend's tmux socket has none of the
  real sessions, so with the real history directory its startup retention
  would delete real history older than a day (it did, on 2026-09-28).

The isolated socket lives under the harness's temporary directory and is
removed at process exit. The default tmux server is not a cleanup signal:
other concurrent QA agents may legitimately own `orrery-qa-*` sessions there.

## v2 contract coverage

The parked v2 cases cover the SPEC contract for session enumeration, the
initial `sessions` event, client `attach` and pane `reset`, keystroke/output
round trips, two-session output isolation, always-on recorder history in a
new client's attach snapshot, recorder cleanup after session death,
graceful-restart history persistence, same-name session created-ts isolation,
unknown-session errors, destructive-operation refusal on a non-test session,
graceful `200`/`502` JSON behavior from the dashboard proxy, the Cycle 3
`/telemetry/health` response shape, and safe `/telemetry/spawn` behavior for
both reachable and offline dashboard states. The two Cycle 3 cases skip on
route-absent `404` (or aiohttp's `405` for the unregistered POST) until their
backend routes land.
