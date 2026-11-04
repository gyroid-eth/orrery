# ORRERY Bridge

The original standalone PTY and control-mode browser prototypes have been
retired in favor of the unified backend and cockpit. `control_server.py`
remains as the shared tmux control plumbing used by the backend and v1 smoke test.

The normal-screen terminal has a visible, draggable native scrollbar on
`.xterm-viewport`. Its thumb reflects that viewport's available scrollback
(up to 6000 browser-side lines), not a provider's entire conversation. The
outer host can pan an oversized Follow grid and stays chromeless.

Alternate-screen TUIs keep the bar hidden, including a late viewer whose
local xterm buffer is normal: tmux reports the remote alternate mode, but
neither tmux nor the terminal stream exposes the TUI's conversation offset
or total length. The recorder's saved rendered rows (up to 2000, with up to
1000 replayed on attach) are also not a complete TUI transcript: redraws can
replace text without scrolling it into history. A read-only history view
would need to label that limited capture, or use a separate provider history
source; it cannot supply an accurate live TUI scrollbar from these rows.

**Settings → Appearance → Conversation history** adds a `History` button to
the pane header (off by default). It opens a read-only Codex transcript next to
the terminal; on narrow screens it fills the pane until closed. The scrollbar
describes the loaded messages, not the live TUI position. `Load earlier` reads
older records, and new output follows only while the reader is at the bottom.
Turn the setting off to remove the button, close the panel and stop its reads.
Conversation scripts/styles are loaded only after opting in. Reading keys stay
in the reader, and opening/closing it does not resize a CLAIMED terminal: the
terminal grid is preserved and its right portion is clipped until History is
closed.
The single preference uses the existing shared preference mechanism; transcript
contents and reading position are never saved as preferences.

The additive `GET /telemetry/conversation?agent=<name>` endpoint accepts an
agent and optional byte cursors (`before` or `after`), never a filesystem path.
In legacy mode only a dashboard `history_binding=bound` Codex row can select
the file; every path component rejects symlinks, and the descriptor stays pinned
through the authoritative binding recheck and a final path/descriptor identity
check. Native rollout filenames must also match their session header. Provider reasoning,
raw tool arguments and raw tool results are omitted; tool names are shown as summaries.
Each read scans at most 4 MiB, returns at most 200 events (80 by default), and
shortens individual messages beyond 64 Ki characters. It never sends terminal
input. Claude Code support is planned for a separate change.

In explicit fresh mode the same endpoint uses the existing protected dashboard
history route and its public text projection, with the bound I/A and current
target rechecked. This mode replaces a recent snapshot of up to 200 text messages,
labels upstream truncation, and does not offer older pages or tool summaries. Full cursor
support there requires extending Telemetry's protected history API rather than
opening raw transcript paths in cockpit. Data acquisition lives in
`conversation_history.py` / `conversation_source.js`, and presentation in
`conversation_view.js` / `conversation_view.css`; the view's optional
`renderEvent(event, defaultRenderer)` adapter allows future reference/preview UI.

### Recorded edits and file preview

**Full width** expands History within the pane. Structured `apply_patch`,
`view_image`, `read_file`, `write_file`, `Read` and `Edit` arguments produce file
chips when permitted. Codex's static `functions.exec` literal wrappers are also
supported, without evaluating JavaScript. Computed calls, shell-command paths,
free-form Markdown, tool-result discovery and embedded/remote attachments are
not reference sources in this version. Claude's binding still needs Telemetry
support; parsing an Edit shape does not enable Claude history.

Diffs show the **recorded edit request**, with **outcome unconfirmed**, never a
diff recomputed from disk or a claim that the tool succeeded. Expand the diff
to see colored added/removed lines. Selecting a file chip expands History and
opens a split preview; **× Preview** returns to the full-width reader. On a
phone the preview takes the reader area until closed. The preview is labeled
**Current file · may differ from the recorded edit**. Reveal is an explicit
button using the existing file-manager adapter.

Full-width History reserves space for the original prompt composer below it;
on phones it places the target above the textarea and STOP/SEND controls.
This is the same DOM element, draft, target, IME handling, send guard and
WebSocket input route as the terminal composer. Reading/preview keys do not
send input. Enter in the composer or an explicit SEND sends, and the normal
history poll picks up the resulting conversation without resetting the reader.

The header shows the status (ACTIVE/LIVE/offline) as a dot and noninteractive
text beside the pane name, with HISTORY (when enabled) and WINDOW on the right.
In a separate pane window, WINDOW returns it to the
cockpit. Terminal-size claim/follow and opening in the external terminal moved
to **Settings → Terminal → Selected pane actions**; the selected session/pane
is shown there, and the same handlers apply. Their defaults did not change:
`applyAutoClaims` claims sessions without an interactive client, follows when
an interactive client appears, and respects the in-memory manual override.
Settings buttons retain keyboard focus during background fit/poll updates.

`conversation_artifacts.py` provides a bounded inert projection;
`conversation_preview.py` issues process-local opaque references;
`conversation_source.js` handles requests; `conversation_preview.js` is the
replaceable renderer/outlet. No Markdown/HTML is executed and no referenced URL
is fetched. Fresh retains its protected recent-text view: its current API has
no structured tool projection, so chips/diffs/preview require a future
Telemetry API extension, not local transcript discovery.

`GET /telemetry/conversation/preview?ref=<id>` and JSON
`POST /telemetry/conversation/reveal` with only `{"ref":"<id>"}` accept no path.
References expire after 15 minutes, are capped at 4096 and are revalidated
against the live binding, pinned transcript inode and original record digest
for every read. Browser input cannot register a reference or broaden a root.

The default preview root is the bound Codex `session_meta.payload.cwd`.
`--conversation-workspace-root /absolute/project` adds an operator-selected
workspace (for example after moving a session to another worktree); it permits
recorded text/raster references under that directory. Repeat
`--conversation-image-root /absolute/images` to permit only recorded raster
references there, not arbitrary text. Both lists are empty by default; neither
option permits scanning or choosing files from the browser. Broad roots such
as `/`, the home directory and `/private/tmp` are rejected. A missing/invalid
root grants nothing. Only exact references from the transcript can be read.

Every preview rechecks canonical containment, rejects symlinks in every path
component, requires a single-link regular file, denies credential-like paths,
and verifies descriptor identity before returning. Text is strict UTF-8 and
at most 128 KiB; SVG/HTML/XML are inert text. PNG/JPEG/GIF/WebP input is at most
8 MiB, 8192 pixels per dimension and 16 million pixels. Only the first frame is
decoded and re-encoded to PNG without original metadata, with an 8 MiB output
limit. Structured extraction is capped at 1 MiB per record, 24 references and
48 Ki characters of diff. Known credential patterns are redacted server-side;
this is a bounded preview, not a guarantee that arbitrary user prose contains
no secrets. Nothing is indexed or stored to disk by these modules.

The reader retains at most 400 events / 2 MiB of serialized event data (fresh:
at most 200). Legacy releases older events while following the bottom; Load
earlier reads them again with per-event cursors. At the limit while reading,
updates pause without moving the reading position; Latest reloads the newest
window and resumes. Loading older pages may release newer ones and pause updates
until Latest. This is a bounded reader, not an archival export.

Each control connection runs through `control_client_guard.py`. The guard owns
one `tmux -CC attach` child and watches a private pipe whose writer belongs only
to the backend. Backend exit (including SIGKILL) closes that pipe; the guard
terminates and reaps its child, escalating to SIGKILL after one second. This
does not rely on PTY hangup: a descendant may still hold the PTY master open.
The guard never scans or signals another cockpit's or user's clients. Each
recorded session adds one backend pipe descriptor and a Python guard measured
at 12.1–12.5 MB RSS with Python 3.12.2 (about 360 MB summed guard RSS for 30
sessions; the cost scales with every recorded session, not just visible tabs).
Each guard wakes every 0.2 seconds, or five times per second. RSS varies with
the Python version and platform. On stop, the backend also terminates remaining
members of its control-client process group if the guard has already died.
It prevents new leaks from this lifetime failure; it does not remove existing
unattributed control clients left by earlier versions.

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

Static responses are limited to the cockpit and tour pages and their bundled
assets. Terminal libraries are pinned locally; versions, hashes and licenses
are recorded in [CREDITS](../CREDITS.md). Write requests use `application/json`.

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

The same-name active-pane jump and direct tmux inventory/Mail descriptions above are legacy behavior. With explicit `AGENTSTACK_RUNTIME_MODE=fresh`, the selected I/A resolves through the existing dashboard's protected host to its current native receipt and fixed pane. Opaque handles and history stay target-specific. Mail reads use finite APIs at the fixed dashboard upstream, without old project/SQLite fallback. See [fresh settings](../docs/en/configuration.md#explicit-fresh-settings-cutover-preparation) and [target protection](../docs/en/runtime-target.md#explicit-fresh-current-targets-and-expiry). Saved settings and private Mail/dashboard/Cockpit startup/shutdown are covered. Real OS managers/Finder GUI, real providers/installations and attended cutover remain unaccepted. Retired reactivation/resume and App GUI foregrounding are outside this cutover scope and remain unavailable.

The unified backend keeps browser traffic same-origin:

| route | source |
| --- | --- |
| `/ws` | tmux control-mode sessions, WS protocol v2 |
| `/telemetry/agents?scope=` | `:8770/api/agents` (`scope=live`: the live rows and the retired names, which the roster poll asks for) |
| `/telemetry/conversation?agent=&before=&after=&limit=` | read-only bound Codex history; `before` and `after` are mutually exclusive |
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
move it when it covers a control. See [Full tour](../docs/en/FULL_TOUR.md) for the
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
