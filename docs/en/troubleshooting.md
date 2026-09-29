# Troubleshooting

> Japanese is the source of truth: [日本語版](../troubleshooting.md)

[Previous: Usage](usage.md) · [Back to README](../../README.en.md) · [Next: Architecture overview](ARCHITECTURE_OVERVIEW.md)

Start by checking the backend and the dashboard separately.

```bash
curl -fsS http://127.0.0.1:8791/telemetry/health
curl -fsS http://127.0.0.1:8770/api/agents
tmux list-sessions
```

`/telemetry/health` reports whether the backend itself and the ORRERY Telemetry dashboard are reachable, as two separate results.

## `ORRERY.app` stays on the offline page

The app checks `:8791/cockpit.html`. If it is unreachable, the app starts the backend in the checkout as a sidecar.

Check:

1. `bridge/.venv/bin/python` exists and is executable
2. `bridge/orrery_backend.py` exists
3. `orrery_root` in `~/.orrery/config.json` points to the actual checkout
4. If you use an env override, `AGENTSTACK_ORRERY_ROOT` or the individual paths are passed to the app process
5. The backend log has no dependency error (for a backend started by ORRERY.app, the log is `~/Library/Logs/ORRERY/backend.log`)

A GUI app does not read `~/.zshrc` and starts with a shorter `PATH` than your shell. When launched from Finder, it uses the shared settings file. A missing config, invalid JSON, a missing Python / script under the root, or a spawn failure writes an actionable reason to the log and leaves the app on the offline page. After fixing the cause, press Retry, or start the backend manually on `:8791`.

## The backend does not start

Start it from the repository root with the correct script path.

```bash
bridge/.venv/bin/python bridge/orrery_backend.py
```

If you run `bridge/.venv/bin/python orrery_backend.py` at the repository root, the script is not found. The latter form works only after `cd bridge`.

Check the dependencies again:

```bash
bridge/.venv/bin/python -m pip install -r bridge/requirements.txt
bridge/.venv/bin/python -c "import aiohttp, websockets, PIL, pyte"
```

Python older than 3.10 cannot parse the union type syntax.

## `pyte` is not found

The terminal recorder uses `pyte`.

```bash
bridge/.venv/bin/python -m pip install "pyte>=0.8.2,<1"
bridge/.venv/bin/python -c "import pyte; print(pyte.__version__)"
```

If `ORRERY.app` uses a different Python, point it at the venv you installed into.

```bash
export ORRERY_BACKEND_PYTHON=/absolute/path/to/orrery/bridge/.venv/bin/python
```

## Port `8791` is in use

Check the listener.

```bash
lsof -nP -iTCP:8791 -sTCP:LISTEN
```

If it is an existing ORRERY backend, you can reuse that process. If it is another service, stop it safely, or change the backend port for browser-only use.

```bash
bridge/.venv/bin/python bridge/orrery_backend.py --port 8801
open http://127.0.0.1:8801/cockpit.html
```

The `ORRERY.app` URL is fixed to `:8791`, so it does not follow a changed port.

## ORRERY Telemetry `:8770` is unreachable

```bash
curl -i http://127.0.0.1:8770/api/agents
```

Check:

- The ORRERY Telemetry dashboard is running
- If you changed `AGENTSTACK_PORT` to something other than `8770`, `ORRERY_DASHBOARD_URL` uses the same port (`scripts/start-cockpit.sh` matches it automatically from `~/.agentstack/env.sh`)
- ORRERY and ORRERY Telemetry run as the same user on the same host

Degradation when it is unreachable:

| Feature | State |
| --- | --- |
| terminal / tmux sessions | available |
| local portrait | available |
| read-only SQLite mail | available if the DB is readable |
| roster / live graph | `dashboard offline` |
| spawn | HTTP 502, unavailable |
| TELEMETRY / REPLAY / dashboard control | unavailable |

Even if you can see the catalog fallback, you cannot spawn while offline. The spawn POST needs the dashboard.

## The `?` / `!` for agents that need you are not visible in NETWORK

In older ORRERY Telemetry builds, depending on the NETWORK layout, the `?` for a waiting question or the `!` for a waiting approval could be hidden behind a neighboring node, so it was sometimes visible and sometimes not. SVG decides on-screen overlap by DOM drawing order, so a node drawn later covered the marker.

The current build always draws nodes that need a human on top. If you can reproduce this on an older build, update ORRERY Telemetry. Before updating, or if NETWORK is hard to read, switch to `DECK`. A waiting question shows as a `?` at the top right of the card, and a waiting approval shows as a red outline and `APPROVAL`. For real screenshots, see [Usage, "Spotting agents that need you"](usage.md#spotting-agents-that-need-you).

## Mail is not shown

ORRERY does not read `AGENTSTACK_MAIL_DB` automatically.

```bash
export ORRERY_MAIL_DB=/absolute/path/to/storage.sqlite3
export ORRERY_PROJECT_KEY=/absolute/path/to/your/project
```

Check:

- The DB file exists and is readable by the backend user
- ORRERY Telemetry and ORRERY use the same absolute path as the project key
- It matches `projects.human_key` in the DB
- `/telemetry/mail/recent` shows no schema error

A missing DB or a schema error does not stop the whole backend. Only the mail route returns `ok:false`.

## The roster is visible but no terminal opens at all

If the following symptoms appear together, check whether the backend can resolve the tmux executable, rather than looking at individual agents.

- The roster and the ORRERY Mail rail display normally
- The header shows `tmux · 0/0`
- The center stays on `waiting for sessions…`
- Starting the backend from a terminal works, but starting `ORRERY.app` from Finder reproduces the problem

A GUI launch from Finder, launchd, or a Tauri sidecar does not read your shell settings and starts with a short `PATH` such as `/usr/bin:/bin:/usr/sbin:/sbin`. So a Homebrew tmux that a terminal finds may not be found by a GUI launch.

The current backend looks for tmux in `PATH` first, then in known install locations, when it starts. If it cannot find one, it prints the `PATH` and the candidates it searched and aborts. To confirm the result for sure, start the backend in the foreground from the repository root. A detached sidecar started from Finder does not save stdout / stderr.

```bash
bridge/.venv/bin/python bridge/orrery_backend.py
```

On success, the following appears right after startup:

```text
ORRERY: tmux resolved to /opt/homebrew/bin/tmux
```

If it is still not found, check the actual location in a terminal, then start the backend with the absolute path in `TMUX_BIN`. You can open `ORRERY.app` while that backend keeps running.

```bash
command -v tmux
TMUX_BIN=/absolute/path/to/tmux bridge/.venv/bin/python bridge/orrery_backend.py
```

`TMUX_BIN` specifies the executable only. It is not an option for passing a custom socket / server; the backend uses the default tmux server of the same user / environment as itself.

If the resolved tmux binary disappears while the backend is running, the following route returns HTTP `503` and `tmux_unavailable` instead of an empty `[]`.

```bash
curl -i http://127.0.0.1:8791/telemetry/sessions
```

## The terminal does not open for only one roster tile

A cockpit jump assumes the agent name matches the tmux session name.

```bash
tmux list-sessions -F '#{session_name}'
```

The following rows have no terminal.

- `surface: codex-app`, which comes from the Codex App Bridge
- An agent whose tmux session has ended
- A manual session with a different name

A Codex App agent can be observed in telemetry but cannot be attached to as a terminal.

Backend startup connects a recorder control client for each live session. In an environment with many sessions, expect the number of tmux clients to grow.

## The terminal wrap width changes

ORRERY's Claim actually changes the tmux window size. Interactive clients such as Ghostty also see the same grid width.

- To prefer the external client, use Follow
- To prefer the ORRERY viewport, use Claim
- Follow restores every distinct ORRERY-owned window to its snapshot taken before Claim
- Closing a session group or closing the app releases owned windows on detach automatically
- The backend also has a tracked-only restore safety net for the last peer detach / disconnect / teardown

Before the first Claim, ORRERY saves whether a local `window-size` option exists, its value, and the exact grid size, and restores that state later. Claiming the same window again does not overwrite the snapshot. Attaching / detaching without a Claim issues no size command, so external manual settings do not change.

If the width does not come back:

1. Check the backend log for `ORRERY window-size restore incomplete` and the session / window ID
2. If the backend is still running after the release failed, retry with Follow or detach
3. Check the current local option with `tmux show-window-options -v -t '<window-id>' window-size`
4. Only if it still could not be restored after the final teardown, check the external setting you had saved and recover it by hand

A tracked snapshot whose restore failed is not consumed until the restore succeeds. Conversely, there is no process that bulk-unsets windows ORRERY does not own.

## The terminal is empty, or xterm does not load

The current frontend loads `xterm.js 5.5.0` and `addon-fit 0.10.0` from a CDN. If the network or the Content Security Policy rejects jsDelivr / Google Fonts, fonts fall back, and without the xterm script the terminal UI cannot work.

Check:

- The browser / WebView developer console
- DNS / TLS reachability to the CDN
- proxy / firewall / CSP

The current distribution is not a fully self-contained offline bundle.

## The WebSocket keeps disconnecting

1. The backend process is alive
2. `/telemetry/health` responds
3. The browser URL and the WebSocket origin are the same
4. The development `?ws=` override is not stale

The client reconnects after 1.5 seconds. In production, use the same-origin `/ws`, and limit `?ws=` to development.

## Split does not add tmux panes

This is normal. The cockpit's Split is a display layout of multiple sessions, not tmux `split-window`.

The protocol's pane `split` / `close` are allowed only for managed sessions with the `orrery-` prefix, and are rejected for ordinary agent sessions.

## Ghostty does not open

The implementation uses a fixed path.

```text
/Applications/Ghostty.app/Contents/MacOS/ghostty
```

There is no override for a binary at another path. If an interactive client is already attached, it does not open a new Ghostty window and returns `already`.

## The prompt is not sent

The composer sends a carriage return 250 ms after the bracketed paste.

- The active pane is the right one
- You are not in the middle of IME composition
- The pane is not at a shell prompt instead of the agent TUI
- The WebSocket is connected

`Shift+Enter` is a newline and `Esc` is an interrupt. Pasting an image does not upload a file; it forwards a literal `Ctrl+V` to the TUI.

## History remains / does not disappear

The terminal recorder saves to `~/.orrery/history` by default and keeps entries for 7 days normally and 24 hours for orphans. The prompt draft / history stay in `localStorage`, and the shared settings stay in `~/.orrery/config.json`. Deleting `ORRERY.app` alone does not remove them.

For what to delete, see [Install, "Data locations and uninstall"](install.md#data-locations-and-uninstall), and do not take ORRERY Telemetry or the ORRERY Mail DB with it.

## Related documents

- [Install](install.md)
- [Configuration](configuration.md)
- [Usage](usage.md)
- [Architecture overview](ARCHITECTURE_OVERVIEW.md)
- [Implementation architecture](ARCHITECTURE.md)
