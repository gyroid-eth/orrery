# Configuration

> Japanese is the source of truth: [日本語版](../configuration.md)

[Previous: Installation](install.md) · [Back to README](../../README.en.md) · [Next: Usage](usage.md)

ORRERY is configured with `~/.orrery/config.json` and environment variables. The shared settings file is also read when the app is launched from Finder, and an environment variable always takes precedence over the same item in the settings file.

In an active Codex pane verified to use the alternate screen without mouse tracking, the wheel sends PageUp / PageDown to scroll the conversation. Small movements accumulate, with at most three pages per continuous gesture; Claude Code, ordinary shells, and Codex panes requesting mouse tracking keep their existing behavior.

## Minimum settings

A minimal example for using all the integrated features:

```bash
export AGENTSTACK_PROJECT_KEY=/absolute/path/to/your/project
export ORRERY_PROJECT_KEY="$AGENTSTACK_PROJECT_KEY"

# If the DB differs from the default
export AGENTSTACK_MAIL_DB=/absolute/path/to/storage.sqlite3
export ORRERY_MAIL_DB="$AGENTSTACK_MAIL_DB"
```

The ORRERY Telemetry dashboard runs at `127.0.0.1:8770`, and the ORRERY backend runs at `127.0.0.1:8791`.

## Shared settings file

The desktop app launched from Finder and the Python backend read the same file.

```text
~/.orrery/config.json
```

An example that specifies every item:

```json
{
  "orrery_root": "/absolute/path/to/orrery",
  "project_key": "/absolute/path/to/your/project",
  "mail_db": "~/.agentstack/mail/storage.sqlite3",
  "annotations_path": "~/.agentstack/runtime/annotations.json"
}
```

| key | component that uses it | purpose |
| --- | --- | --- |
| `orrery_root` | Tauri shell | The base for `bridge/.venv/bin/python` and the backend script |
| `project_key` | Python backend | The project human key of ORRERY Mail |
| `mail_db` | Python backend | The read-only ORRERY Mail SQLite |
| `annotations_path` | Python backend | The annotation fallback when the dashboard is unreachable |

Only arbitrary string keys of a top-level JSON object are accepted. Empty strings, non-strings, and unknown keys are ignored; leading and trailing whitespace is removed and `~` is expanded. A missing, unreadable, or invalid-JSON file does not stop startup and is treated as unset. Because it contains path information, file mode `0600` is recommended.

### Desktop app environment

`AGENTSTACK_ORRERY_ROOT` and `ORRERY_BACKEND_*` exported in `~/.zshrc` are not passed to a Finder launch. A normal Finder launch uses `orrery_root` in `config.json`; use the env override with `npm run dev`, or when you start the executable inside the app bundle directly from the same terminal.

## Runtime / build variables

| environment variable | default | purpose |
| --- | --- | --- |
| `ORRERY_MAIL_DB` | `config.mail_db`, then `~/.agentstack/mail/storage.sqlite3` | The ORRERY Mail SQLite that ORRERY opens read-only. There is no fallback to `AGENTSTACK_MAIL_DB` |
| `ORRERY_PROJECT_KEY` | `AGENTSTACK_PROJECT_KEY`, then `config.project_key`, finally unset | `projects.human_key` for mail queries. In a user's environment, specify an absolute path |
| `AGENTSTACK_PROJECT_KEY` | `config.project_key`, then unset | The common fallback for the ORRERY project key. The same value as ORRERY Telemetry is recommended |
| `ORRERY_PORTRAIT_DIR` | `<repo>/assets/portraits_64` | Normal portraits |
| `ORRERY_PORTRAIT_DIR_HI` | `<repo>/assets/portraits` | `hi=1` portraits |
| `ORRERY_PORTRAIT_DIR_PX` | `<repo>/assets/portraits_px` | `style=pixel` portraits |
| `AGENTSTACK_ANNOTATIONS` | `config.annotations_path`, then the ORRERY Telemetry runtime / legacy path | A file fallback read only when the dashboard annotation API is unreachable |
| `ORRERY_HISTORY_DIR` | `~/.orrery/history` | Where the terminal recorder saves its JSON |
| `AGENTSTACK_ORRERY_ROOT` | `config.orrery_root`, then unset | The root where the Tauri sidecar looks for the checkout |
| `ORRERY_BACKEND_PYTHON` | `<root>/bridge/.venv/bin/python` | The sidecar's Python |
| `ORRERY_BACKEND_SCRIPT` | `<root>/bridge/orrery_backend.py` | The sidecar's backend script |
| `ORRERY_TMUX_SESSION` | unset | The attach session of the legacy `control_server.py`. Not used by the product backend |
| `ORRERY_PORTRAIT_SOURCE_DIR` | `<repo>/assets/portraits_src` | The input of `scripts/build_portraits.py` |

There is no fallback to any owner-specific path. You state the needed root / project explicitly in env or the shared settings file, so that degradation when they are unset can be diagnosed.

## Generic environment variables and CLI

These do not have the `ORRERY_*` prefix, but they are part of the startup contract.

| target | environment variable / option | default | note |
| --- | --- | --- | --- |
| desktop / backend | `HOME` | the OS user home | The base for `~/.orrery/config.json` and `~` expansion |
| unified backend | `HOST` | `127.0.0.1` | Other addresses are rejected |
| unified backend | `PORT` / `--port` | `8791` | `ORRERY.app` does not follow a change |
| unified backend | `TMUX_BIN` / `--tmux-bin` | `tmux` | A binary path only. Not a custom tmux socket option |
| legacy control server | `HOST` | `127.0.0.1` | Not a product server |
| legacy control server | `PORT` | `8780` | For development use |
| legacy control server | `TMUX_BIN` | `tmux` | The tmux executable |
| legacy control server | `SESSION` | unset | Takes precedence over `ORRERY_TMUX_SESSION` |

An example of changing the backend port:

```bash
PORT=8801 bridge/.venv/bin/python bridge/orrery_backend.py
# or
bridge/.venv/bin/python bridge/orrery_backend.py --port 8801
```

In a browser you can open the changed URL directly, but the desktop app is fixed to `:8791`.

## Test-only variables

| environment variable | default | purpose |
| --- | --- | --- |
| `ORRERY_E2E_V2` | unset | Set to `1` to enable the unified-backend contract suite |
| `ORRERY_STREAM_ROUNDS` | `5` | The number of rounds in the stream integrity test |

```bash
cd bridge
ORRERY_E2E_V2=1 .venv/bin/python tests/e2e_bridge.py -v
```

## Connection priority

### project key

1. `ORRERY_PROJECT_KEY`
2. `AGENTSTACK_PROJECT_KEY`
3. `project_key` in `config.json`
4. Unset

In a user's environment, set one of 1 to 3 as an absolute path. When it is unset, the mail API returns `ok:false` and `project key not configured`. If you set a value different from ORRERY Telemetry's, the roster and the mail rail may point at different projects.

### ORRERY Mail DB

ORRERY reads `ORRERY_MAIL_DB`, then `mail_db` in `config.json`, then the default path, in that order. ORRERY Telemetry's `AGENTSTACK_MAIL_DB` is not inherited automatically, so for anything other than the default, set the same path on both sides.

SQLite is opened read-only in this form:

```text
file:<path>?mode=ro
```

A missing DB or a schema error does not stop the whole backend; the mail route returns `ok:false`.

### annotation fallback

It resolves `AGENTSTACK_ANNOTATIONS`, then `annotations_path` in `config.json`. If you specify either explicitly, only that one file is used.

If neither is set, it uses the first readable file in this order.

1. `~/.agentstack/runtime/annotations.json`
2. `~/.claude/tools/agent-dashboard/annotations.json` (legacy)

This file fallback is used only when the dashboard's `/api/annotations` is unreachable.

### ORRERY Telemetry dashboard

ORRERY's destination is fixed to:

```text
http://127.0.0.1:8770
```

Do not change the port on the ORRERY Telemetry side. The APIs it needs are `/api/agents`, `/api/messages-since`, `/api/graph`, `/api/spawn`, `/api/spawn-names`, `/api/annotations`, and `/api/exit`.

### tmux

You can change the executable with `TMUX_BIN`, but there is no public option to specify a socket / server. It uses the default tmux server of the same user / environment as the backend process. The cockpit jump assumes that the agent name and the tmux session name match.

## portrait

Portraits are read from these directories:

- Normal: `ORRERY_PORTRAIT_DIR`
- High resolution: `ORRERY_PORTRAIT_DIR_HI`
- Pixel style: `ORRERY_PORTRAIT_DIR_PX`

If there is no matching PNG, an initials SVG is returned. To regenerate the source assets, use `ORRERY_PORTRAIT_SOURCE_DIR`; the manifest, SHA-1, and provenance are verified. A portrait not listed in the manifest and `CREDITS.md` is not regarded as an asset approved for distribution. However, the 50 pixel-art images in `assets/portraits_px/` were generated by the author, gyroid, with ChatGPT (OpenAI's image generation) from text instructions alone. No photographs were used as input. They are distributed under the same terms as the repository (PolyForm Perimeter License 1.0.1).

## Stored data and privacy

The terminal recorder flushes pane JSON to `ORRERY_HISTORY_DIR` every 30 seconds.

- Up to 2000 lines are kept per pane
- The attach snapshot is up to 1000 lines
- Normal history is kept for 7 days
- Orphans with no corresponding session are kept for 24 hours

The prompt composer saves a draft and up to 50 sent-history entries in browser `localStorage`. Font, split layout, the mini-orrery mode / depth, and the open / closed state of NEW AGENT's Advanced panel are also saved in `localStorage`. `~/.orrery/config.json` is a user setting that remains even after the app is deleted.

On a shared Mac, during screen sharing, or with confidential sessions, consider the following:

- Change `ORRERY_HISTORY_DIR` to an encrypted, user-only directory
- Separate the browser profile
- Clear the prompt history / localStorage after use
- Do not screen-share while the mail rail and terminal are showing
- For screen sharing and recordings, use demo mode

Demo mode (Demo mode in Settings, or `?demo=1` in the URL; `?demo=0` turns it off for that page) masks your user name and machine name on screen with the same number of `*`. It masks the user name inside a home path (`/Users/<name>`, `/home/<name>`, `C:\Users\<name>`), in the form `<name>@`, and the machine name as a word of its own. The names come from the backend's `GET /telemetry/identity`, which reads them from `$HOME`, the login name and the host name (and, on WSL, the Windows user name); nothing is guessed. A name inside another word, and people's names written in text, are not masked. Only the display changes: agents, records and Mail stay as they are, and clicking a path or URL in a terminal, and copying, use the real values. A text field keeps its real value and shows a masked copy over it (sending, editing and copying use the real value). Nothing is shown until the names are known; if the backend cannot return them, the page stays hidden and shows the reason with Retry (choose "Open without demo mode" to see the page unmasked). The Settings switch is saved in browser `localStorage`.

To hide other words too (a person's name written in Mail, a project name), add them, separated by `,`, under "Also mask these words" in Settings (saved in browser `localStorage`). They are hidden like the user name: the same number of `*`, in terminal contents too, and clicks and copies get the real text back. A word of letters and digits is hidden in any letter case, only as a whole word (`Kobo`, but not inside `kobold`). A word with any other character, such as Japanese, which has no spaces between words, is hidden wherever it appears (adding `ミラノ` also hides it in `ミラノさん`). One-character words are ignored. For one page you can also pass `?mask=word,word` in the URL, but a URL stays in history and in anything you share, so prefer the Settings field.

For where data is saved and what remains after deletion, see also ["Data locations and uninstall" in Installation](install.md#data-locations-and-uninstall).

## Localhost safety boundary

The backend refuses to bind to anything other than `127.0.0.1`, but there is no authentication inside localhost. Because access reaches terminal input, spawn, EXIT, filesystem directory listing, and the dashboard control proxy, do not expose it through a remote proxy or port forwarding.

`/telemetry/fs/dirs` excludes hidden directories, but unlike the browser on the dashboard side, it has no root allowlist. Keep the localhost-only boundary.

## Related documents

- [Installation](install.md)
- [Usage](usage.md)
- [Troubleshooting](troubleshooting.md)
- [Architecture overview](ARCHITECTURE_OVERVIEW.md)
- [Implementation architecture](ARCHITECTURE.md)
