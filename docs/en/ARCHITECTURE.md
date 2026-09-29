# Implementation architecture

> Japanese is the source of truth: [日本語版](../ARCHITECTURE.md)

[Previous: Architecture overview](ARCHITECTURE_OVERVIEW.md) · [Back to README](../../README.en.md) · [Next: Design language](DESIGN.md)

How tmux, Codex App, the network, data retention, and portrait images are handled is in the [Architecture overview](ARCHITECTURE_OVERVIEW.md), and the security assumptions are in the [README](../../README.en.md#security-and-privacy). This document is for contributors and covers only the implementation responsibilities of the backend, routes, WebSocket, and tmux control.

## Components

| component | path | responsibility |
| --- | --- | --- |
| unified backend | `bridge/orrery_backend.py` | aiohttp origin, telemetry proxy, mail, portrait, tmux session manager |
| tmux control plumbing | `bridge/control_server.py` | control-mode parsing, pane stream, input / resize |
| cockpit | `bridge/cockpit.html` | layout and entry point |
| frontend logic | `bridge/orrery_view.js`, `bridge/mail_view.js` | roster, terminal, graph, mail, interaction |
| desktop shell | `app/` | Tauri window, shared config, offline page, sidecar, global hotkey |
| history store | `ORRERY_HISTORY_DIR` | terminal recorder JSON |

The backend does not import ORRERY Telemetry's source; it treats the dashboard as an external HTTP service.

## Startup sequence

1. Verify that the bind host is `127.0.0.1`
2. Register the static / HTTP / WebSocket routes
3. List the live sessions of the default tmux server
4. Connect a recorder control client for each session
5. Restore persisted terminal history by matching it against the session identity
6. Wait for browser clients to connect

Pane attach is deferred until the browser selects a session. A recorder connection exists for each live session and keeps the history up to date at all times.

## HTTP routes

| method / path | implementation responsibility |
| --- | --- |
| `GET /ws` | WebSocket protocol v2 |
| `GET /telemetry/agents` | Fetch `:8770/api/agents` and merge annotations and the question determination |
| `GET /telemetry/messages?since=&limit=` | `:8770/api/messages-since` |
| `GET /telemetry/graph?all=&days=` | `:8770/api/graph` |
| `GET /telemetry/spawn-catalog` | `:8770/api/spawn-names` with the local Codex catalog overlaid |
| `POST /telemetry/spawn` | Proxy a JSON object to `:8770/api/spawn` |
| `POST /telemetry/open-ghostty` | Validate the session and attach in Ghostty |
| `GET /telemetry/health` | Backend and dashboard reachability. `boot` is an identifier of the backend process (the same value as the `X-Orrery-Boot` header on every response; the page watches it for changes and reloads itself) |
| `GET` / `PUT /telemetry/prefs` | Cockpit settings shared between the app window and browser tabs (`~/.orrery/prefs.json`). PUT takes `{"set": {...}, "remove": [...]}`. Keys are whitelisted, and values are strings only |
| `GET /telemetry/usage?refresh=` | Claude / Codex account usage quota. Cached for 60 seconds per provider; on failure the previous value is kept and marked `stale`. `refresh=1` bypasses the cache |
| `GET /telemetry/mail/recent?limit=&agent=` | Recent messages from the project-scoped SQLite. limit 1–100, default 40 |
| `GET /telemetry/mail/message?id=` | Message detail / recipients |
| `GET /telemetry/mail/thread?thread_id=&limit=` | Thread. Default / maximum 50 / 100 |
| `GET /telemetry/portrait?name=&hi=&style=pixel` | Local PNG or initials SVG |
| `GET /telemetry/sessions` | tmux inventory and the interactive client flag |
| `GET /telemetry/skills` | Built-in skills and `~/.claude/skills/*/SKILL.md`. Cached for 30 seconds |
| `GET /telemetry/fs/dirs?path=` | Directory browser excluding hidden entries. Up to 200, no root allowlist |
| `* /network` | Embed of the ORRERY Telemetry dashboard root |
| `* /network/<tail>` | Passthrough under the ORRERY Telemetry dashboard root |
| `* /api/<tail>` | ORRERY Telemetry API passthrough |
| `* /assets/<tail>` | ORRERY Telemetry asset passthrough |
| `GET /portrait` | ORRERY Telemetry portrait passthrough |
| `STATIC /<path>` | `bridge/` static files. Includes `/cockpit.html`, with directory index enabled |

Passthroughs accept every method, but only POST has its request body read. Upstream response headers other than `Content-Type` and cache control are not preserved.

The only upstream contract of `/telemetry/spawn-catalog` is ORRERY Telemetry's `/api/spawn-names`. A 404 is returned as is, and there is no fallback to another live-only route.

## WebSocket protocol

`/ws` handles the protocol v2 session inventory and pane streams.

client operations:

- attach / detach
- refresh
- input
- resize
- release
- close

server events:

- sessions inventory
- pane reset / snapshot
- incremental output
- layout / lifecycle update
- operation result / error

An unknown session returns an error. Each browser client is limited to 12 sessions for attach / split.

## tmux safety

The backend uses the default tmux server. `TMUX_BIN` / `--tmux-bin` replace the executable; they are not a socket selector.

For ordinary sessions, attach, read, input, resize, and refresh are allowed. Pane `split` / `close` are allowed only when the session name starts with `orrery-`, and closing the last remaining pane is refused.

The backend never creates or kills sessions on its own. The legacy `control_server.py` creates a test session when no session is specified, so do not use it as a product launch path.

## Recorder and restore

The recorder updates a `pyte` screen and flushes JSON every 30 seconds.

- Pane history: up to 2000 lines
- Attach snapshot: up to 1000 lines
- Normal retention: 7 days
- Orphan retention: 24 hours

To avoid wrongly restoring stale history for a session of the same name, the session creation identity is matched, not just the session name and pane ID.

While a Claim is active, the window size is pinned with `resize-window`. The backend's `SessionState.claimed_windows` holds, per window ID, the `WindowSizeSnapshot` taken just before the first Claim. The snapshot is the presence and value of the local `window-size` option, plus the exact grid width / height. A repeated Claim on the same window does not overwrite it.

On Follow, auto release, group close, roster prune, and `beforeunload`, the frontend makes the panes in a session distinct by window ID and then sends a common release. The backend's explicit release restores only the tracked windows of the target pane, while the last peer's detach / disconnect and teardown restore all the tracked windows. For a plain attach / detach without a Claim, the ownership map is empty, so no window-size command is issued, including for windows with an externally set manual option.

Restore proceeds in this order: `resize-window` to the snapshot size, updating the control client's per-window size, and restoring the original local option. If the original was unset, `set-option -u` is used; if it was set, the original value such as `manual` is set again. Only entries that succeed are consumed from the ownership map. Whether the restore fails after the first resize, in a rollback, a release, a detach, or a teardown, the snapshot is kept so it can be retried, and any window IDs left at the final teardown are logged to stderr.

## Frontend runtime

The cockpit loads `xterm.js 5.5.0` and `addon-fit 0.10.0` from a CDN. The terminal logic assumes the scripts have loaded, so if you change to a self-contained distribution, update asset vendoring, CSP, license notices, and bundle inclusion together.

The prompt draft / history remain only in each window's `localStorage`. Font, auto-shrink, split layout, mini mode / depth, color theme, theme profile, and the open / closed state of NEW AGENT Advanced are synchronized by `bridge/prefs_sync.js` with the backend's `/telemetry/prefs` (`~/.orrery/prefs.json`). On load it copies the values into `localStorage` with a synchronous GET, intercepts `setItem` to PUT, and picks up changes from other windows with a GET every 4 seconds, dispatching `oc:prefs-changed`. This prevents a recurrence of the problem where the app window and a browser tab hold separate settings and look different. Reset applies only to font and auto-shrink.

## ORRERY Telemetry failure boundary

Dashboard requests are proxied through the ORRERY backend. A dashboard failure is not escalated to a terminal failure.

| upstream failure | ORRERY behavior |
| --- | --- |
| agents / graph / message API unreachable | Show offline; terminals continue |
| spawn unreachable | 502; no agent is created |
| embed root unreachable | TELEMETRY is unavailable |
| annotation API unreachable | Try file fallbacks in order: env / config / ORRERY Telemetry runtime / legacy |

The spawn catalog's local fallback is for the modal display and is not a fallback for running a spawn.

## Security boundary

- Bind is limited to `127.0.0.1`
- No authentication within localhost
- Static files expose all of `bridge/` with a directory index
- `/telemetry/fs/dirs` has no root allowlist
- Dashboard control routes are passed through
- Only the ORRERY Mail SQL is read-only

If you change the localhost-only restriction, authentication, CSRF, origin, the directory browser, terminal input, mail bodies, and the control API must be redesigned together.

## Test support

tmux-free frontend mock:

```bash
python3 bridge/tests/mock_backend.py
```

unified backend contract:

```bash
cd bridge
ORRERY_E2E_V2=1 .venv/bin/python tests/e2e_bridge.py -v
```

stream stress:

```bash
cd bridge
ORRERY_E2E_V2=1 ORRERY_STREAM_ROUNDS=20 \
  .venv/bin/python tests/e2e_bridge.py -v
```

The E2E tests use a dedicated tmux socket and uniquely named test sessions. Do not make the default tmux server or real agent sessions a cleanup target.

In an environment where `pytest` is installed separately, the same file can also be run with `-m pytest`. `bridge/requirements.txt` does not include `pytest`, so the standard-library run path is used as the basic example.

## Responsibilities of each document

- This document: source components, routes, protocol, implementation constraints
- [Design language](DESIGN.md): visual tokens, motion, state expression
- [Usage](usage.md): user operations
- [Configuration](configuration.md): the full list of environment variables
