# Installation

> Japanese is the source of truth: [日本語版](../install.md)

[Back to README](../../README.en.md) · [Next: Configuration](configuration.md)

## Install or update with one line

In a Mac terminal, or inside WSL2 Ubuntu on Windows, run this one line. It installs both orrery-telemetry and the cockpit, checks that they work (doctor, and a selftest that sends Mail both ways), then starts the cockpit **in the background**, prints its URL and opens the browser. The window comes back, so you can install Claude Code and log in right there. Where ORRERY is already (partly) installed, the same line updates it (telemetry only, an old version, an old checkout without setup.sh, a detached HEAD).

```bash
curl -fsSL https://raw.githubusercontent.com/gyroid-eth/orrery/master/scripts/get.sh | bash
```

- **What is trusted and what runs**: only GitHub's `gyroid-eth/orrery` and `gyroid-eth/orrery-telemetry` (a checkout whose origin is not exactly one of these is left alone, and the setup stops). What runs: `get.sh`, the cockpit's `scripts/setup.sh`, orrery-telemetry's `scripts/install.sh`, and uv's official installer only when uv is missing
- **Look without changing anything**: `curl -fsSL …/get.sh | bash -s -- --check` (prerequisites and the plan), `… | bash -s -- --dry-run` (plus the installer's preview of the 4 changes). Neither writes to your home folder (what they download goes to a temporary folder that is removed)
- **CI and scripts that use the exit code**: `curl | bash` can return 0 when the download fails, so save first: `curl -fsSL …/get.sh -o get.sh && bash get.sh --yes`
- Prerequisites (git, tmux, curl, uv, Python 3.11+) are checked at once. Missing git / tmux / curl stop it with nothing changed and the line that installs them. uv and Python need no sudo, so they go into the plan (your shell profile is not changed)
- Before changing anything it shows one plan; **type `yes` and Enter** once. Four things change: `~/.claude.json` (MCP), `~/.claude/settings.json` (hooks and permissions), `~/.codex/AGENTS.md` (a global block for all your Codex work), and the project's `CLAUDE.md` (a block). Each is backed up first. `--ask-each` also shows each change and asks; `--yes` does not ask (you have read the plan) (`… | bash -s -- --ask-each`)
- The folder agents work in is `~/orrery-work` unless you say otherwise (no question; the plan shows it). Another folder: `… | bash -s -- --project-key ~/my-project`
- The cockpit runs in a tmux server of its own (`tmux -L orrery-cockpit`), apart from the agents' tmux, so it never shows up as an agent. Its output: `tmux -L orrery-cockpit attach` (Ctrl-b, d to leave). Stop it: `tmux -L orrery-cockpit kill-server`. Start it again: the same line. On an update, a cockpit this setup started is restarted on the new version (any other cockpit is left running, with a note)
- The 2 test agents the selftest makes are not shown in the cockpit's roster and network (the dashboard still lists them)
- The doctor's exit status decides (anything but 0 is shown and is not ready). A run whose update failed is never ready either, even if you start what you have
- At the end it shows, for each of the 4 changes, applied / already the same / skipped; whether Mail was set up or the running one kept; and the doctor and selftest results. Without Claude Code or Codex it says the base is ready, agents are not yet
- If a cockpit of another version that this setup did not start is already running, it is not stopped; you are told to press Ctrl-C in its window and run the same line again
- **When something fails**: a check that fails before you type yes means the setup changed nothing (what `get.sh` did before it stays, and the screen says so: a newly downloaded cockpit checkout, or git data fetched into an old one). After that, **nothing is rolled back**: you get a table of what changed since the first attempt and the line that carries on (the first attempt's record, in `~/.orrery-install/`, is kept until a run passes every check). There is no command to go back to the previous version
- To remove a new install, use the printed `<orrery-telemetry checkout>/scripts/uninstall.sh` (the Mail database stays unless `--purge-data`; the 2 checkouts, uv and Python stay). **Do not use it to undo an update**: it removes the whole install

The rest of this section installs step by step by hand.

## For first-time installers (browser, Mac / Windows WSL2)

This section alone takes you from nothing to ORRERY installed on your own Mac or Windows 11 PC and the cockpit open in a browser. Each command is in its own code block, and copying and pasting them in order works. It does not use the desktop app (`ORRERY.app`). Even on a Mac, you open it in the browser. For building or keeping the app running, see "Requirements" and the sections after it.

### 0. Obsidian (when you use it)

If you will use ORRERY together with Obsidian (a note-taking app), install Obsidian first. If you will not, skip to "Mac" or "Windows 11" (ORRERY works without Obsidian).

- **Mac**: download the Mac version from https://obsidian.md/ and move it to Applications
- **Windows 11**: download the Windows installer from https://obsidian.md/ and run it. Install Obsidian on the **Windows side** (not inside the WSL2 Ubuntu)

### Mac

Paste the commands below into Terminal (press Cmd+Space, type "Terminal"), one at a time, and press Enter after each.

**1. Homebrew and tmux**

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Enter your Mac password when asked (nothing appears as you type). Press Enter when it tells you to. Apple's command line tools (including git) are installed at this point. At the end the installer prints "Next steps" with the PATH setup; the next three lines are the same thing (for an Apple silicon Mac; skip them on an Intel Mac; if the installer shows something different, follow what it shows).

```bash
echo >> ~/.zprofile
```

```bash
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
```

```bash
eval "$(/opt/homebrew/bin/brew shellenv)"
```

```bash
brew install tmux
```

**2. ORRERY**

```bash
curl -fsSL https://raw.githubusercontent.com/gyroid-eth/orrery/master/scripts/get.sh | bash
```

A plan appears. Read it, type `yes`, and press Enter. It takes from tens of seconds to a few minutes, and the cockpit opens in your browser. If something is missing (git, tmux, curl), it changes nothing, stops, and shows how to install it. When it stops, run the one "how to continue" line it shows.

**3. Claude Code**

```bash
curl -fsSL https://claude.ai/install.sh | bash
```

If you see `claude: command not found`, add it to your PATH (or follow the PATH note the installer printed at the end):

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
```

```bash
source ~/.zshrc
```

```bash
claude
```

Sign in, answer every first-run question (text style, security notes, trusting the folder, and so on), and when the input prompt appears, type `/exit`. If you close it halfway, a Claude started from NEW AGENT in the cockpit stops at the first-run screen. If you use Codex, install Codex CLI and run `codex login` (ORRERY's last screen shows how to install it).

From here, `+ NEW AGENT` in the cockpit starts agents. If you use Obsidian, continue with "Using it with Obsidian".

### Windows 11

ORRERY runs in Ubuntu on Windows (WSL2), and its screen appears in a Windows browser. Obsidian runs on the Windows side.

**1. WSL2 Ubuntu**

In the Start menu, right-click "PowerShell", choose "Run as administrator", and paste:

```powershell
wsl --install
```

When it finishes, restart the PC. Open "Ubuntu" from the Start menu and choose a user name and password for Ubuntu (nothing appears as you type the password). If you already have Ubuntu, skip up to here. **From here on, type everything in the Ubuntu window** (`username@PC:~$`). Install the tools (nothing happens if they are already there):

```bash
sudo apt update && sudo apt install -y git tmux curl
```

**2. ORRERY**

```bash
curl -fsSL https://raw.githubusercontent.com/gyroid-eth/orrery/master/scripts/get.sh | bash
```

A plan appears. Read it, type `yes`, and press Enter. It takes from tens of seconds to a few minutes, and the cockpit URL (`http://127.0.0.1:8791/cockpit.html`) is printed. If your Windows browser does not open by itself, paste that URL into it. If something is missing, it changes nothing and stops, so run the one "how to continue" line it shows.

**3. Claude Code** (install it inside Ubuntu. A Claude Code or Codex installed on the Windows side is not used)

```bash
curl -fsSL https://claude.ai/install.sh | bash
```

If you see `claude: command not found` (or follow the PATH note the installer printed at the end):

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
```

```bash
source ~/.bashrc
```

```bash
claude
```

Sign in (if no browser opens, paste the URL it shows into your Windows browser), answer every first-run question, and when the input prompt appears, type `/exit`. If you use Codex, install Codex CLI inside Ubuntu and run `codex login` (a `codex` from Windows' npm (`/mnt/c/...`) does not work from WSL).

From here, `+ NEW AGENT` in the cockpit starts agents. If you use Obsidian, continue with "Using it with Obsidian".

### Using it with Obsidian

The same on Mac and Windows (on Windows, type it in the Ubuntu window). This installs the research set: digest-paper, which turns papers into reading notes, and a practice Obsidian vault. Add `--lang en` for the English vault and requests (without it, Japanese).

```bash
curl -fsSL https://raw.githubusercontent.com/gyroid-eth/orrery/master/scripts/research-set.sh | bash -s -- --lang en
```

At the end it shows where to open the vault in Obsidian and the requests to paste to an agent. The vault is `~/Documents/orrery-demo-vault-en` on a Mac (`orrery-demo-vault` without `--lang en`), and a folder of the same name in the Windows Documents folder on Windows (the Windows form of the location is printed at the end).

In Obsidian, choose "Open folder as vault" and open the vault at the location shown. When asked about community plugins, choose "Trust author and enable plugins". That vault becomes the agents' work folder, so an agent you start from then on with `+ NEW AGENT` in the cockpit works inside the vault (agents that were already running stay on the old folder, so start new ones). See [The research set](research-set.md) for details.

### Install by hand (from getting the repository)

These are the steps without the one line above: you get the repository and install by hand.

#### 0. Install orrery-telemetry first

ORRERY cockpit reads the agent list, NEW AGENT (spawn), Mail, and usage quota from [ORRERY Telemetry](https://github.com/gyroid-eth/orrery-telemetry) (the repository is named orrery-telemetry; it was formerly called AgentStack, and the `AGENTSTACK_*` environment variables and `~/.agentstack` are remnants of that name). **Finish the orrery-telemetry [installation steps](https://github.com/gyroid-eth/orrery-telemetry/blob/master/docs/install.md) all the way through before you continue.** On Windows, follow the "Install on Windows (WSL2)" section of that document and install inside the WSL2 Ubuntu.

The cockpit is built against the latest orrery-telemetry release. **If you already have orrery-telemetry, update it first** (in the orrery-telemetry repository, run `git pull` and then `./scripts/install.sh`; once the cockpit is installed, `./scripts/update.sh` in step 5 updates both at once). With an older version, parts of the cockpit do not work; for example, a finished Codex agent cannot be resumed.

`scripts/start-cockpit.sh` (step 2) checks two things at every start. Neither stops the start.

- **The API generation**: when the `api` in the dashboard's `/api/version` (the generation of the API the cockpit relies on) is lower than the cockpit needs, missing, or unreadable, it prints a `WARN` with the update command (`scripts/update.sh`, step 5)
- **A newer release**: it looks up the latest orrery-telemetry release on GitHub and prints a `note` when it is newer than yours. The answer is kept for a day in the venv folder (`bridge/.venv`). Without a network, or when GitHub is slow, it prints nothing. To skip this lookup, start with `ORRERY_NO_UPDATE_CHECK=1`

You are ready when all four of these are true:

- `~/.agentstack/bin/agentstack-doctor` reports no problems
- Opening `http://127.0.0.1:8770/` in a browser shows the orrery-telemetry dashboard
- `curl -s http://127.0.0.1:8770/api/version` reports `"api": 2` or higher; 1 means any release from before this scheme (ideally with the same `version` as the [latest release](https://github.com/gyroid-eth/orrery-telemetry/releases/latest))
- Claude Code's first-run setup is finished (start `claude` and go through text style, login, Security notes and trusting the folder until the normal input prompt appears, answer any other one-time question it asks, such as trying the fullscreen renderer, then `/exit`), or you are logged in to Codex CLI (`codex login`). If the setup was left halfway, a Claude agent from NEW AGENT stops on the setup screen and does not start. ORRERY never answers these questions for you. On Windows, log in to the copy **installed inside Ubuntu**. A copy installed on the Windows side is not used

#### What to keep the same: same machine, same user, same tmux

The cockpit looks directly at the tmux sessions of the agents that orrery-telemetry started. So keep all of the following the same.

- **The same OS environment**: on Windows, the same WSL2 Ubuntu where you installed orrery-telemetry. On a Mac, the same Mac
- **The same user**: the user who installed orrery-telemetry (do not start the cockpit with `sudo` or as another user)
- **The same tmux server**: start agents with `agent-start` / `agent-start-codex` or the cockpit's NEW AGENT. Do not use a different tmux server through `tmux -L name` or `TMUX_TMPDIR`

#### 1. Put ORRERY on your machine

Get the repository.

```bash
git clone https://github.com/gyroid-eth/orrery.git orrery
cd orrery
```

Until the repository is made public, only a GitHub account that has been invited can fetch it.

On Windows, type this **at the Ubuntu prompt (`user@PC:~$`)**. Put it under the Ubuntu home directory (for example `~/orrery`). Avoid placing it under `/mnt/c/...` (a Windows drive): it is slow and handles permissions differently.

#### 2. Run the start script

Inside the repository:

```bash
./scripts/start-cockpit.sh
```

In one run, the script does the following.

1. Checks the prerequisites (Python 3.10 or newer, tmux, the orrery-telemetry settings, the project key, and a response from the dashboard; an older orrery-telemetry only gets a warning)
2. Creates a Python environment in `bridge/.venv` and installs the packages in `bridge/requirements.txt` (the first run takes a while; from the second run on it skips this if nothing changed)
3. Takes over the orrery-telemetry settings (the project key, Mail DB, and dashboard port in `~/.agentstack/env.sh`). It does not rewrite settings files under `~/.agentstack` or `~/.orrery`
4. Starts the backend **inside this window**, confirms it responds, and then prints the URL to open

When it works, the end of the output looks like this.

```text
==============================================================
  ORRERY cockpit is running. Open this URL in your browser:

    http://127.0.0.1:8791/cockpit.html
...
==============================================================
```

#### 3. Open it in the browser

Open the printed `http://127.0.0.1:8791/cockpit.html` in your browser.

- Mac: open it in Safari or Chrome
- Windows: open it in Edge or Chrome **on the Windows side**. `127.0.0.1` in WSL2 is forwarded to the Windows side, so it reaches the cockpit as is

If no agents appear in the list on the left, start one from the cockpit's NEW AGENT, or run `~/.agentstack/bin/agent-start /path/to/your-project` (`agent-start-codex` for Codex) in another window.

#### 4. Stop it and start it again

- To stop, press `Ctrl-C` in the window where the script is running. Closing that window also stops it
- **Leave the window you started it in open.** The cockpit runs inside that window (it does not stay resident)
- On Windows, agents, the dashboard, and Mail started from Windows Terminal keep running in the background after you close the Ubuntu windows. When you are done and want WSL to give its memory back to Windows, run `wsl --shutdown` in PowerShell. After that, or after restarting the PC, open Ubuntu and check the state with `~/.agentstack/bin/agentstack-doctor`. If something has stopped, start it with `~/.agentstack/dashboard/agentctl.sh start` and `~/.agentstack/bin/agentstack-mailctl start`, and then run `./scripts/start-cockpit.sh` again

#### 5. Update

Run this in the cockpit folder. It brings orrery-telemetry and the cockpit up to date in one go.

```bash
./scripts/update.sh
```

When it is done, press `Ctrl-C` in the window running the cockpit, and run `./scripts/start-cockpit.sh` again.

##### Details

- orrery-telemetry is updated first: `git pull --ff-only` and `./scripts/install.sh` where it was installed from.
- Then the cockpit: `git pull --ff-only`.
- Your previous settings are kept. The project key, dashboard port, Mail URL and so on are read from `~/.agentstack/env.sh`.
- A value you have set in your current shell is used instead.
- If you installed the Codex plugin, it is refreshed too.
- At the end, it shows the orrery-telemetry version and the cockpit commit.
- It stops with the reason, changing nothing, in any of these cases: uncommitted changes, untracked files the update would overwrite, a branch that cannot be fast-forwarded, or a remote it cannot reach.
- If orrery-telemetry's `install.sh` fails, the cockpit is not updated.
- `./scripts/update.sh --dry-run` only shows what it would do and changes nothing.
- If `bridge/requirements.txt` has changed, `start-cockpit.sh` installs the packages again the next time you start it.
- If the dashboard does not answer, check it with `~/.agentstack/bin/agentstack-doctor` and start it with `~/.agentstack/dashboard/agentctl.sh start`.
- To update by hand, run `git pull` and `./scripts/install.sh` in orrery-telemetry, then `git pull` in the cockpit. The Codex plugin refresh is in orrery-telemetry's [docs/codex-app.en.md](https://github.com/gyroid-eth/orrery-telemetry/blob/master/docs/codex-app.en.md).

### When something is missing

The script checks the prerequisites all at once, shows what is missing on lines marked `NG`, and stops without starting anything. Below each `NG` line, a `Fix:` line tells you how to fix it.

| Message (excerpt) | Meaning and fix |
| --- | --- |
| `Python 3.10 or newer is required.` | Python is too old or missing. On a Mac, `brew install python@3.13`; on Ubuntu, `sudo apt install python3`. To use a specific Python, run `ORRERY_PYTHON=/path/to/python3 ./scripts/start-cockpit.sh` |
| `tmux is not installed.` | On a Mac, `brew install tmux`; on Ubuntu, `sudo apt install tmux` |
| `orrery-telemetry is not installed` | `~/.agentstack/env.sh` does not exist. Install orrery-telemetry first (step 0) |
| `No project key is configured.` | Reinstall orrery-telemetry with its installer, adding `--project-key /absolute/path/to/your-project` |
| `Something answers at ..., but it is not the orrery-telemetry dashboard.` | Another program is answering on the dashboard's port. Check the dashboard's state and port with `agentstack-doctor` |
| `The orrery-telemetry dashboard does not answer` | Check the state with `agentstack-doctor` and start it with `agentctl.sh start` (you can use the printed command as is) |
| `Port 8791 is used by another program.` | A program other than the cockpit is using 8791. Start on another port, such as `PORT=8796 ./scripts/start-cockpit.sh`, and open the printed URL |
| `cannot create a venv (ensurepip is missing)` | The Ubuntu Python lacks the venv components. Install `sudo apt install python3.X-venv` as shown (if `uv` is available the script uses it to create the environment, so this message does not appear) |
| `Installing the Python packages failed` | Check your network and run it again |

A line marked `note` is not a reason to stop. For example, `neither 'claude' nor 'codex' is on PATH` means agents cannot be started from NEW AGENT. Install Claude Code or Codex CLI, log in, and run the script again.

If a cockpit is already running on the same port, the script does not start a second one; it only prints the URL to open and exits.

To check the prerequisites and prepare the Python environment without starting the backend, add `--check`.

```bash
./scripts/start-cockpit.sh --check
```

### Differences on Windows (WSL2)

- Operation on WSL2 is still being verified on Windows 11 with WSL2 Ubuntu (as of 2026-09-28)
- The "open in a window" button in the cockpit opens a Windows Terminal (`wt.exe`) tab instead of Ghostty on a Mac. If you do not have Windows Terminal, install it from the Microsoft Store
- Pasting files and images does not work on WSL2. Pasting ordinary text does
- Shortcuts such as `Cmd+K` become `Alt+K` and so on. For the list of differences, see ["Differences on Windows (WSL2)" in Usage](usage.md#differences-on-windows-wsl2)

## Requirements

`ORRERY.app` is officially supported on macOS. The Python backend assumes Unix / tmux and has no macOS-only guard. Using it in a browser on Windows WSL2 (Ubuntu) is also still being verified ([For first-time installers](#for-first-time-installers-browser-mac--windows-wsl2)). Other operating systems are not guaranteed as a product.

Required:

- Python 3.10 or newer
- `tmux`
- `pip` and `venv`
- A network that can reach the runtime CDN

For developing and building the desktop app:

- Node.js and npm
- The Rust toolchain and Cargo
- The Tauri v2 platform prerequisites

To use all features:

- [ORRERY Telemetry](https://github.com/gyroid-eth/orrery-telemetry)
- ORRERY Mail SQLite
- A tmux session running Claude Code or Codex CLI

The Node and Rust versions are not pinned in the repository. Use your organization's standard toolchain and fix a combination for which `npm ci` and the Cargo build both pass.

## Repository and Python environment

Clone the repository.

```bash
git clone https://github.com/gyroid-eth/orrery.git
cd orrery
```

Create a virtual environment for the backend only.

```bash
python3 -m venv bridge/.venv
bridge/.venv/bin/python -m pip install --upgrade pip
bridge/.venv/bin/python -m pip install -r bridge/requirements.txt
```

The main Python dependencies are as follows.

| package | version range | purpose |
| --- | --- | --- |
| `aiohttp` | `>=3.9,<4` | static / telemetry HTTP and WebSocket |
| `websockets` | `>=12,<16` | tmux control bridge |
| `Pillow` | `>=10,<12` | portrait helper |
| `pyte` | `>=0.8.2,<1` | terminal recorder / screen state |

## Connect to ORRERY Telemetry

By default, ORRERY uses `http://127.0.0.1:8770` as the ORRERY Telemetry dashboard URL. If you set ORRERY Telemetry's `AGENTSTACK_PORT` to something other than `8770`, specify the destination with `ORRERY_DASHBOARD_URL` before starting the backend (a trailing `/` is ignored).

```bash
export ORRERY_DASHBOARD_URL=http://127.0.0.1:8780
```

If `ORRERY_DASHBOARD_URL` is not set, `scripts/start-cockpit.sh` sets it automatically from `AGENTSTACK_PORT` in `~/.agentstack/env.sh`. The sidecar of `ORRERY.app` does not read shell environment variables when launched from Finder, so keep `8770` if you combine it with the app.

Set the same absolute project key on both sides.

```bash
export AGENTSTACK_PROJECT_KEY=/absolute/path/to/your/project
export ORRERY_PROJECT_KEY="$AGENTSTACK_PROJECT_KEY"
```

If the ORRERY Mail DB is somewhere other than the default `~/.agentstack/mail/storage.sqlite3`, specify it on the ORRERY side as well, in addition to ORRERY Telemetry's `AGENTSTACK_MAIL_DB`.

```bash
export AGENTSTACK_MAIL_DB=/absolute/path/to/storage.sqlite3
export ORRERY_MAIL_DB="$AGENTSTACK_MAIL_DB"
```

Start ORRERY Telemetry first, and then check:

```bash
curl -fsS http://127.0.0.1:8770/api/agents
```

Even if ORRERY Telemetry is stopped, ORRERY's terminal, tmux inventory, local portraits, and the mail route that reads SQLite directly still work. The roster, spawn, embedded TELEMETRY, REPLAY, and dashboard control degrade or stop.

## Start the backend by itself

From the repository root:

```bash
bridge/.venv/bin/python bridge/orrery_backend.py
```

Or move into `bridge/`:

```bash
cd bridge
.venv/bin/python orrery_backend.py
```

The default URL is:

```text
http://127.0.0.1:8791/cockpit.html
```

To check:

```bash
curl -fsS http://127.0.0.1:8791/telemetry/health
open http://127.0.0.1:8791/cockpit.html
```

You can change the standalone backend's port with `PORT` or `--port`, but `ORRERY.app` always opens `:8791`. Do not change it if you combine it with the desktop app. Only `127.0.0.1` is allowed for `HOST`.

## Build the desktop app

```bash
cd app
npm ci
npm run build
```

Output location:

```text
app/src-tauri/target/release/bundle/macos/ORRERY.app
```

The current bundle is ad-hoc signed; it is not signed with a Developer ID and is not notarized. For distribution inside an organization, add your own signing / notarization pipeline.

Development run:

```bash
cd app
npm ci
npm run dev
```

## Set the sidecar path

`ORRERY.app` does not contain the backend or a venv. If `:8791` does not respond, it starts the Python and script inside the checkout as a detached sidecar.

An app launched from Finder / LaunchServices does not read the shell's `~/.zshrc` or the values exported there. For a Finder launch, save the checkout root in the shared settings file.

```json
{
  "orrery_root": "/absolute/path/to/orrery"
}
```

It is saved at `~/.orrery/config.json`. Create the directory and save it as a top-level JSON object. The app derives `bridge/.venv/bin/python` and `bridge/orrery_backend.py` from `orrery_root`.

Resolution order:

1. `ORRERY_BACKEND_PYTHON` / `ORRERY_BACKEND_SCRIPT` (each path is overridden individually)
2. A path relative to `AGENTSTACK_ORRERY_ROOT`
3. `orrery_root` in `~/.orrery/config.json`
4. If unset or the path does not exist, it logs an actionable reason and shows the offline page

The env variables are overrides for a development launch, or a direct launch from a terminal, where the app process inherits them.

```bash
AGENTSTACK_ORRERY_ROOT=/absolute/path/to/orrery \
  /Applications/ORRERY.app/Contents/MacOS/ORRERY
```

If the Python or the script cannot be found, the app shows the bundled offline page and re-checks `:8791` every 3 seconds. In that case you can start the backend by hand and Retry. The sidecar stays alive even after the app window is closed, so manage the process explicitly if you want to end it.

## Check and install the release bundle

From the repository root, run a dry run first.

```bash
./scripts/install-app.sh --dry-run
./scripts/install-app.sh
```

After confirmation, the script replaces `/Applications/ORRERY.app` with `rsync -a --delete`. It does not escalate privileges, and it only prints the `codesign` and `open` commands. If needed, you can skip the confirmation with `-y`.

## global hotkey

The app tries to register the following keys in order and uses the first one that is available.

1. `Cmd+Shift+O`
2. `Cmd+Ctrl+O`
3. `Cmd+Alt+O`
4. `Cmd+Shift+F19`

The app starts even if all of them fail. Check the startup log for the binding that was adopted, and verify hide / show manually once.

## Data locations and uninstall

Deleting `ORRERY.app` alone does not delete the related checkout, backend, history, ORRERY Telemetry, or tmux sessions.

| Item | Default location / state | After the app is deleted |
| --- | --- | --- |
| desktop app | `/Applications/ORRERY.app` | Deleted |
| source checkout / venv | the clone directory, `bridge/.venv` | Remains |
| ORRERY shared settings | `~/.orrery/config.json` | Remains |
| detached backend | the `orrery_backend.py` process | May stay alive even after the app is closed |
| terminal history | `~/.orrery/history` | Remains |
| prompt draft / up to 50 history entries | WebView / browser `localStorage` | May remain as profile data |
| font / layout / mini / NEW AGENT Advanced / colour theme settings | `~/.orrery/prefs.json` (held by the backend and mirrored to each WebView / browser `localStorage`) | The app window and browser tab share the same values. They also remain on the localStorage side |
| tmux sessions | the user's default tmux server | Not killed; they remain |
| ORRERY Telemetry / ORRERY Mail DB | their own install / data paths | ORRERY does not delete them |

Before deleting, detach the session groups and stop the backend. The frontend sends a release to every distinct window that ORRERY has Claimed and then detaches. The backend also restores only the tracked windows on the last peer detach / disconnect / teardown. What it restores is the exact grid size just before the first Claim and the local `window-size` option. For a window that was only attached / detached without a Claim, it issues no size command and keeps any manual settings of external clients as they are.

A snapshot whose restore failed is kept for a retry on a later path. If it cannot be restored even at teardown, the backend records the session name and window ID on stderr, so check the backend log and the tmux window options.

To delete the optional data too, check each item individually before you delete it.

1. `ORRERY.app`
2. ORRERY's source checkout and `bridge/.venv`
3. `ORRERY_HISTORY_DIR` (default `~/.orrery/history`)
4. `~/.orrery/config.json`
5. The WebView / browser localStorage for the ORRERY origin

ORRERY Telemetry, the ORRERY Mail DB, and the user's tmux sessions are shared infrastructure and user data. Do not delete them in ORRERY's uninstall steps.

## Related documents

- [Configuration](configuration.md)
- [Usage](usage.md)
- [Troubleshooting](troubleshooting.md)
- [Architecture overview](ARCHITECTURE_OVERVIEW.md)
- [Implementation architecture](ARCHITECTURE.md)
