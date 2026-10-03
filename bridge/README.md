# ORRERY Bridge

The original standalone PTY and control-mode browser prototypes have been
retired in favor of the unified backend and cockpit. `control_server.py`
remains as the shared tmux control plumbing used by the backend and v1 smoke test.

## Setup

```sh
cd bridge
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
```

## Cockpit (live telemetry chrome + live terminal)

`cockpit.html` is the integrated ORRERY cockpit. One unified backend serves the
page, telemetry routes, and the WS protocol v2 endpoint from the same origin:

- **Center terminal** — live `xterm.js` terminals from multiple lazily attached
  tmux sessions over `/ws`. Tabs are grouped by session (agent) name; selecting
  a tab fills the CRT screen with that pane. The group `×` detaches the cockpit
  from that session without killing it.
- **Crew roster + agent-mail rail + mini-orrery** — read live from the running
  agent-dashboard through the unified backend's `/telemetry/*` proxy. Tiles show
  each agent's engine, model, context-window, context-used %, state
  (working/ask/idle by motion), and current task; the rail accumulates recent
  agent-mail; portraits are served straight off disk.
- **Roster jump** — clicking an agent tile focuses the active pane in the
  same-named tmux session. If needed, the cockpit attaches first and focuses
  after that session's `reset`. Agents without a live session get a brief
  `offline` hint and no modal error.
- **Spawn lineage** — the `spawn` edges from `/api/graph` give each agent a
  parent; the medallion colour is shared across a spawn-tree root (hue per root,
  assigned only across the *visible* roots so the palette never collides on
  screen), and the mini-orrery clusters agents by lineage with a line drawn on
  each parent→child spawn edge. (Colour is reserved for lineage by convention;
  state is shown by motion, not colour.)

The unified backend keeps browser traffic same-origin:

| route | source |
| --- | --- |
| `/ws` | tmux control-mode sessions, WS protocol v2 |
| `/telemetry/agents` | `:8770/api/agents` |
| `/telemetry/messages?since=&limit=` | `:8770/api/messages-since` |
| `/telemetry/graph?all=&days=` | `:8770/api/graph` (spawn lineage) |
| `POST /telemetry/spawn` | JSON object proxy to `:8770/api/spawn`; dashboard response passes through |
| `/telemetry/health` | backend status plus dashboard reachability |
| `/telemetry/sessions` | live tmux session inventory |
| `POST /telemetry/open-url` | `{url}` → default browser via `open` (http/https only; used by the pane link addon) |
| `POST /telemetry/reveal-path` | `{path}` → Finder: a file is revealed (`open -R`), a folder opened. Absolute or `~` paths that exist; never launched |
| `POST /telemetry/path-probe` | `{text}` → longest existing path prefix of a printed row (resolves unquoted paths with spaces) |
| `/telemetry/portrait?name=&hi=&style=pixel` | `assets/portraits_64/`, `assets/portraits/`, or `assets/portraits_px/` on disk |

```sh
cd bridge
. .venv/bin/activate
python orrery_backend.py             # cockpit + telemetry + WS on :8791
```

Open `http://127.0.0.1:8791/cockpit.html`. The WebSocket defaults to the
same-origin `/ws`; override it for development with the `ws` query parameter,
for example `cockpit.html?ws=ws://127.0.0.1:8803/ws`. The cockpit auto-reconnects
if the backend drops and degrades gracefully (roster tag shows
`dashboard offline`, terminal shows `disconnected`) rather than going blank.

**Settings → Getting started → Full tour** opens the sixteen-step workshop
checklist, separate from Your first flight. It covers /delegate shiritori over
ORRERY Mail, pane arrangement and Telemetry's crew/history controls. Fold or
move it when it covers a control. See [Full tour](../docs/FULL_TOUR.md) for the
order, completion boundaries and embedded Telemetry requirement.

For a tmux-free frontend check, run the protocol-v2 mock:

```sh
cd "$(git rev-parse --show-toplevel)"
python3 bridge/tests/mock_backend.py
```

Open `http://127.0.0.1:8803/cockpit.html`. The mock provides three sessions,
fake roster/mail/graph telemetry, scripted terminal output, and input echo. It
never inspects or changes real tmux state.

### Clickable links in panes

Pane output is scanned by two xterm link providers (2026-09-05):

- **URLs** (`@xterm/addon-web-links`): hover underlines, click opens the
  default browser through `POST /telemetry/open-url`. The Tauri webview has no
  `window.open` handler, so the backend does the opening; a browser-hosted
  cockpit falls back to `window.open` if the backend refuses.
- **Local paths** (`/abs/…` or `~/…`): click reveals the path in Finder through
  `POST /telemetry/reveal-path`. Bare one-segment tokens such as `/compact`,
  `/log` or the statusline's `/rc` are not linked (a path needs a second `/`
  or an extension). When the rest of the row contains spaces or non-ASCII
  text, the row is sent to `POST /telemetry/path-probe`, which returns the
  longest existing prefix, so `…/21_Coding Projects/orrery/logs はうまくいかない`
  links exactly `…/orrery/logs`. Results are cached per row text.

Limits: a path wrapped across rows is not linked; relative paths
(`dashboard/server.py:12`) are not resolved (would need the pane's cwd).
Agents that want a location to be clickable should print it absolute.

## Unified Backend

`orrery_backend.py` combines the static cockpit, telemetry proxy, and tmux
control bridge on one aiohttp origin. It attaches tmux sessions lazily when a
WebSocket client requests them and shares one control-mode connection per
session. The default endpoint is `http://127.0.0.1:8791/` with protocol-v2
WebSockets at `/ws`.

```sh
cd bridge
. .venv/bin/activate
python -m pip install -r requirements.txt
python orrery_backend.py
```

Use `--port` (or `PORT`) to override the port:

```sh
python orrery_backend.py --port 8801
```

The backend never creates or kills tmux sessions. Destructive pane operations
(`split` and `close`) are accepted only for sessions whose names start with
`orrery-`; normal agent sessions allow attach, detach, read, input, resize,
refresh, and release only.

### Grid width claim

tmux panes share one character grid across every attached client, and tmux
sizes the grid to the most recently active interactive client — so with a
Ghostty window attached, the cockpit would inherit Ghostty's wrap width. On a
`resize` message the backend therefore pins the window size explicitly
(`resize-window -x -y`), which wins even against an attached narrower client
(verified: 80 → 160 cols with an 80-col client attached). While the cockpit
views a pane, an attached Ghostty window shows that pinned size.

Before ORRERY first claims a window, the backend records that window's exact
grid size and whether a local `window-size` option was present (including its
value). Repeated claims of the same window do not replace this snapshot. Follow
and explicit release restore only ORRERY-owned windows to their saved grid and
local option; a plain attach/detach that never claimed a window leaves external
manual settings unchanged. Last-peer detach, disconnect, and backend teardown
provide the same tracked-only restore safety net. A failed restore retains its
snapshot for a later retry, and an incomplete teardown logs the session and
remaining window IDs. See [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md#recorder-と復元)
for the full ownership and restore contract.
