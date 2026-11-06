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
the pane header (off by default). It opens a read-only provider conversation next to
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
agent and optional opaque cursors (`before` or `after`), never a filesystem path.
In legacy mode only a dashboard `history_binding=bound` row can select a source.
API 35 or later adds Claude Code JSONL, dsh V4 JSONL/concatenated Zstd frames and
Hermes SQLite alongside Codex. An older dashboard retains Codex support and
explicitly reports the other readers as unsupported. Stale bindings show
**Previous conversation**, with the reason and no body; unbound records also
show a reason without reading a source. Native session ID and receipt timestamp
participate in context resets, cursor fingerprints and binding rechecks.

Every source path component rejects symlinks, and the descriptor stays pinned
through the authoritative binding recheck and a final path/descriptor identity
check. Native metadata must match the bound session. Provider reasoning and raw
tool arguments/results are omitted. Calls show names; results show completion
or failure summaries. Messages are shortened beyond 64 Ki characters.

- **Codex:** existing byte cursor behavior and protected fresh projection remain.
- **Claude:** complete JSONL record/block cursors; native `sessionId` is checked.
  Sidechain/meta records and thinking blocks are excluded. `Read`, `Write` and
  `Edit` calls can produce confined file chips and recorded edit-request diffs.
- **dsh:** V4 only, human-source user messages and assembled assistant text.
  This is a **recorded append timeline**, not reconstruction of the model's
  current context: replacement/compaction/injection events are excluded.
  Independent frames have frame/line/block cursors. Each request bounds compressed
  input and decoded output to 4 MiB and 512 frames; an unfinished final frame
  stays pending. Invalid complete frames fail explicitly. `zstandard==0.23.0`
  is pinned in requirements; if missing, dsh reports unsupported without a
  guessed decoder or provider executable. Recorded fs-result hunks are supported.
- **Hermes:** exact `history_session_id` on every message query, `mode=ro`,
  query-only SQL, no migrations, writes or WAL checkpoints. Committed WAL rows
  remain visible. The reader replaces a bounded **active bound-segment snapshot**
  (up to 200 events / 4 MiB scanned), reflecting edits/rewinds. It excludes hidden,
  model-only, inactive and summary rows; it does not follow compression ancestry
  or claim full Hermes display fidelity. There are no earlier pages in this mode.

Other cursor pages return up to 200 events (80 by default), with a 4 MiB scan
window. No reader sends terminal input. SQLite can use its normal read-only
WAL/SHM coordination; the reader does not promise immutable sidecar lock bytes.
Hermes checks the regular path against its pinned no-follow descriptor immediately
before/after SQLite connect and after reading. A same-UID process can hide a fully
restored ABA inside connect; this local reader does not defend against a process
that already has direct access to the original provider database.

In explicit fresh mode the same endpoint uses the existing protected dashboard
history route and its public text projection, with the bound I/A and current
target rechecked. This mode replaces a recent snapshot of up to 200 text messages,
labels upstream truncation, and does not offer older pages or tool summaries. Full cursor
support there requires extending Telemetry's protected history API rather than
opening raw transcript paths in cockpit. Data acquisition lives in
`conversation_history.py` / `conversation_readers.py` / `conversation_source.js`, and presentation in
`conversation_view.js` / `conversation_view.css`; the view's optional
`renderEvent(event, defaultRenderer)` adapter allows future reference/preview UI.

### Split terminals

Each desktop split cell has its own HISTORY button and independent reader.
Side panel, Full width and file/image preview stay inside that cell; other
cells retain their terminal grids. Several histories can remain open at once.
Interacting with a reader selects its cell through the existing pane focus
route, so the original composer below the grid shows that pane as its target.
Its send guards and API are unchanged. A narrow reader replaces its thread
with the selected preview until closed. Closing one history leaves the grid
and other histories intact. Readers belong to their live pane, so closing a
different pane or rebuilding the split layout keeps the surviving reader,
full/side mode, expanded Mail and selected preview. Hidden tabs retain bounded
reader state while suspending reads; removed/replaced panes and Settings OFF
dispose their readers. Width changes may shift the reading position by one or
two lines.

Submitting through the original composer closes only the target reader's preview
and resumes Latest, including a reader paused at its retention limit. Messages
still come solely from provider records. Paste and delayed Enter use the same
captured pane/session; removal, replacement or connection change cancels Enter
with a visible notice. Deferred image paste also keeps its original target.

### Find a recorded message in its terminal

Click message text or a tool summary (or focus it and press Enter/Space) to
search only that pane's current xterm buffer. Soft-wrapped rows are joined and
whitespace is normalized. A unique literal match scrolls to and selects the
physical rows, without input, resize, claim or tmux copy-mode. Wide readers
return to side mode; narrow readers close only their own history. Bottom restores
normal terminal following. No-match and multiple-match notices leave History
open. Native text selection, double click and file/diff controls keep their own
actions. The search scans at most 6500 rows / 2 MiB; removed rows and old
alternate-screen frames are unavailable. Markdown rendering and truncation can
prevent a literal match.

### Recorded Mail cards

`conversation_mail.py` projects exact notification prefixes in user text and
qualified ORRERY `send_message` calls from Codex, Claude, dsh and Hermes. It emits
`kind: mail`, a bounded `mail` list and the existing event ID/cursors. Each item
contains direction, sender/recipients, subject, importance, recorded body,
coverage (`complete`, `preview`, `unavailable`, `request`) and a truncation flag.
Only these named fields leave tool arguments; auth and raw results are omitted.
Static literal calls inside Codex `functions.exec` are supported without eval;
computed arguments and unrelated services remain ordinary tool summaries.

`conversation_mail.js` renders collapsible text-only cards. A notification is
recorded text, not authenticated delivery evidence; send requests say delivery
is unconfirmed. Body text is capped at 64 Ki characters each / 128 Ki per tool
record, at most eight sends. Preview and missing-body notices direct the reader
to Mail. No Mail API/DB access, inbox/ack consumption, attachment loading or new
send API is added. Fresh can classify notifications in its protected text
projection; outgoing tools still need a protected tool projection there.

Unbound/stale responses carry the dashboard reason code to the source module,
which renders a short next action (new child, wait/retry, or Codex plugin/hooks
setup). It does not offer rebinding or infer a transcript path.

### Recorded edits and file preview

Claude `SendUserFile` creates chips from its explicit `files: string[]`.
Caption, status and result prose grant no paths. These chips use the same
workspace/image roots, canonical-path, secret-file, byte and pixel limits as
other recorded references; delivery does not expand the readable roots.

**Full width** expands History within the pane. Structured `apply_patch`,
`view_image`, `read_file`, `write_file`, `Read` and `Edit` arguments produce file
chips when permitted. Codex's static `functions.exec` literal wrappers are also
supported, without evaluating JavaScript. Computed calls, shell-command paths,
free-form Markdown and embedded/remote attachments are not reference sources.
Only structured calls and dsh's known filesystem result-hunk metadata grant
references; generic result bodies never grant file access.

Call diffs show the **recorded edit request**, with **outcome unconfirmed**.
dsh filesystem-result diffs are labeled **Recorded file tool result · contextual
hunk**. Neither is recomputed from disk or treated as proof of the current file. Expand the diff
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
An open reader also shows a separate, in-memory **Sent → target · Awaiting record**
receipt after the existing paste and Enter path succeeds. It stays visible until
a matching new user record arrives; after 60 seconds its label becomes **Not recorded yet**.
It is not provider acknowledgement.
With a provider that records whole seconds, a record written in the same second as the send may show as not matched. Repeated prompts match one record each;
old loaded records and older pages cannot consume a new receipt. Whitespace is
normalized; a sufficiently long truncated prefix can match an unambiguous send. Closing and
reopening History retains receipts; changing binding, closing the pane or
turning History off discards them. If a new user record cannot be associated confidently, the receipt says
**Record not matched** rather than claiming the record is still absent. The receipt displays at most 1,000 characters; exact
matching is available for prompts up to the reader's 64 KiB text limit.

Assistant text supports a small inert projection of GFM tables: a matching
header/delimiter row is required, malformed row widths and fenced/indented code
stay text. Cells render as text only, including HTML and link syntax. A following fence, heading, quote or list ends the table. Wide
tables retain their horizontal position across polling and pane relocation; **Copy Markdown** copies the original table.
Terminal jump still searches the original complete provider message. Tables
have a 64-column / 500-row projection limit; larger shapes remain text.

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

The default preview root is the bound native workspace: Codex's
`session_meta.payload.cwd`, Claude's first native message `cwd`, dsh's session
header `cwd`, or Hermes's exact `sessions.cwd`. A missing cwd grants no default root.
`--conversation-workspace-root /absolute/project` adds an operator-selected
workspace (for example after moving a session to another worktree); it permits
recorded text/raster references under that directory. Repeat
`--conversation-image-root /absolute/images` to permit only recorded raster
references there, not arbitrary text. Both lists are empty by default; neither
option permits scanning or choosing files from the browser. Broad roots such
as `/`, the home directory and `/private/tmp` are rejected. A missing/invalid
root grants nothing. Only exact references from the transcript can be read.

Every preview rechecks canonical containment, rejects symlinks in every path
component, requires a single-link regular file
and verifies descriptor identity before returning. Text is strict UTF-8 and
at most 128 KiB; SVG/HTML/XML are inert text. PNG/JPEG/GIF/WebP input is at most
8 MiB, 8192 pixels per dimension and 16 million pixels. Only the first frame is
decoded and re-encoded to PNG without original metadata, with an 8 MiB output
limit. Structured extraction is capped at 1 MiB per record, 24 references and
48 Ki characters of diff. File names and contents are shown as recorded, with
no name-based hiding or content redaction: the owner decides. Nothing is
indexed or stored to disk by these modules.

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
| `/telemetry/conversation?agent=&before=&after=&limit=` | read-only bound provider history; `before` and `after` are mutually exclusive |
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

J1 stops without moving when either its row/character search budget or query
length limit prevents checking the entire retained buffer. A partial search
cannot prove a unique match. Mail calls inside a composite `functions.exec`
add cards while retaining the original tool, file references and recorded diff.
The fixed ORRERY aliases include the bound `agentstack` proxy's send tool;
arbitrary services named `send_message` remain ordinary tools.

Split panes have their own title bars: the name and status identify the pane,
HISTORY reads that pane, and WINDOW moves that session into its own window.
The shared upper header is hidden while two or more splits are visible. A
single pane retains the existing header. Pane names still support drag reordering
and closing; their keyboard focus action uses Enter or Space. Title bars stay 40px high at every width. Names and status ellipsize; narrow
panes use HIST/WIN labels and the smallest panes use labelled icons.
Turning conversation history off removes HISTORY while keeping WINDOW available.
