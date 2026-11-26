# Getting started with Telemetry on its own

![Inspect agent status in the standalone Telemetry dashboard](../images/telemetry/images/deck_growing.png)

To start with Telemetry on its own, run the shared installer, set up your provider, and look for the agent in DECK.

[日本語](../getting-started.md) · [Documentation index](README.md) · [README](../../README.en.md)

For the usual entry point, use the [ORRERY cockpit quick start](install.md#install-or-update-with-one-line). One line installs cockpit and Telemetry together; try Your first flight → help map → Full tour on screen. This page is the standalone Telemetry procedure and a reference for background and terms.

## Who this is for

- **People who want to use coding agents** can set up Claude Code, Codex, Gemini, DeepSeek, or Local LLM agents that write code, change files, and run commands. You can start here even if this is your first agent.
- **A good fit**: you run several agents and find yourself acting as the go-between: pasting Codex output into Claude Code, or hopping between apps and tabs to check on each one. You want that manual relay gone and the whole picture on one screen.
- **Not a fit**: one agent is enough for you. The value here is in coordinating several agents and watching them.
- **Supported agents** include Claude Code and Codex through their own CLIs, Gemini through Google Antigravity CLI (`agy`), and DeepSeek and Local LLMs through dsh or Hermes.
- **Codex Desktop tasks and subagents** can appear on the same dashboard through an optional provider.

## Choose by goal

First [install and verify the shared components](#standalone-installation-and-verification), then prepare your chosen provider.

| Provider | After the shared install |
| --- | --- |
| Claude Code / Codex | Install and sign in to the chosen CLI, then [start the first agent](#3-start-the-first-agent-and-watch-it-on-the-dashboard) |
| Gemini (Antigravity) | The shared install includes the integration files. Install and sign in to Antigravity CLI, then launch from NEW AGENT. [Gemini setup guide](antigravity.md) |
| DeepSeek / Local LLMs | Follow [API setup](native-setup.md) for dsh/Hermes, key storage and connection settings, then launch from NEW AGENT. Claude/Codex login is not required |

Open DECK / NETWORK to observe configured agents. To connect them, continue with the [Mail check](#5-play-shiritori-as-an-end-to-end-check). Check the [supported API combinations and limitations (Japanese)](https://github.com/gyroid-eth/orrery-telemetry/blob/master/docs/managed-catalog.md) too.

<a id="provider-model-harness"></a>
## Provider, model and harness

| Choice | Meaning and current examples |
| --- | --- |
| provider / backend | Connection and credential settings. `claude`, `codex`, and `gemini` use their CLI's sign-in. `deepseek` and `strata` (displayed as Local) use a configured API connection |
| model | A formal model ID selected from the models configured for the same backend |
| harness | The CLI that runs the conversation and tools. DeepSeek and Local API connections use `dsh` or `hermes`. Claude Code, Codex CLI, and Antigravity CLI each use their own harness |

The model's maker need not be the API host: a DeepSeek model hosted locally still uses Local as its connection. Agent identity, parent, work project and Mail recipient are separate from these choices. Selecting a model or harness does not select a parent or recipient.

API spawning uses legacy mode with macOS Keychain or explicitly configured Linux Secret Service references; it separately requires backend, runtime and credential configuration. Arbitrary API × harness combinations are not promised. New Hermes children use a separate HOME per project and canonical name. Common login and Telegram entry points are in design; real-server acceptance of manual Local effort remains incomplete. See the [current limitations (Japanese)](https://github.com/gyroid-eth/orrery-telemetry/blob/master/docs/managed-catalog.md#現在の制限) and the [Model / Harness screen examples and selection GIF](dashboard.md#native-models-and-harnesses).


## Six words

These six terms help you read this standalone procedure and the reference guides.

| Term | Meaning |
| --- | --- |
| agent | One session running through Claude Code / Codex CLI, dsh / Hermes, or another supported runtime. Each gets a scientist's name. |
| child | Another agent that an agent started by asking it to do a job. The one that asked is the parent. A parent creates a child with `/delegate`; when the child is done it reports back to the parent. See [what happens after completion](dashboard.md#after-a-child-completes). |
| ORRERY Mail | The small bundled server through which agents message each other and that manages names and file reservations. |
| dashboard | The page you open in a browser. It shows every agent's state, the parent-child tree, and the messages going back and forth. |
| project key | The absolute path of the project folder the agents work on. It is the key that tells which project an agent belongs to. |
| skill | A playbook that tells an agent "when asked like this, follow these steps". You call one with a leading slash, as in `/delegate`. This tool ships two: `/delegate` and `/log` ([playbook details](launchers.md#skills-2-and-file-reservations)). |


## Standalone installation and verification

Use Python 3.11 or later, `git`, `tmux`, and `uv`. Check the [OS prerequisites](install.md#requirements) for `curl`, `lsof`, and `xz`. On macOS you can add uv with `brew install uv`. If you use uv's official installer, run `export PATH="$HOME/.local/bin:$PATH"` in the same shell and verify with `uv --version`.

**On Windows**, run the commands below in WSL2 Ubuntu and open the dashboard in your Windows browser. After [preparing WSL2](telemetry-install.md#installing-on-windows-wsl2), follow the setup for your provider. Sign in to the CLI for Claude or Codex, follow the [Gemini setup guide](antigravity.md), or complete [API setup](native-setup.md) for DeepSeek or Local.

### 1. Install

```bash
git clone https://github.com/gyroid-eth/orrery-telemetry.git
cd orrery-telemetry
./scripts/install.sh --project-key /absolute/path/to/your-project
```

`--project-key` is the absolute path of the project folder you want the agents to work on, not the path of this repository.

The [consent contract](instruction-migration.md#consent) defines the confirmation conditions. Existing settings are kept, with a backup in `~/.agentstack/backups`. Add `--dry-run` to preview changes.

**Success**: the last line reads `Install complete: http://127.0.0.1:8770/` and `~/.agentstack/` exists.

### 2. Check that it works

```bash
export PATH="$HOME/.agentstack/bin:$PATH"
agentstack-doctor
agentstack-selftest
```

**Success**: the required `agentstack-doctor` checks show `ok:` with no `missing:` entries; inspect any `warn:` entries and their suggested fixes (informational `note:` and `mail-features:` lines are also normal), and `agentstack-selftest` ends with `self-test passed: two agents registered, exchanged messages, ...`. If either stops, go to the matching section of [Troubleshooting](telemetry-troubleshooting.md).

### 3. Start the first agent and watch it on the dashboard

**For Gemini**, the `install.sh` command above installs the integration files. Follow the [Gemini setup guide](antigravity.md) to install and sign in to Antigravity CLI. Choose **Antigravity** and a model in NEW AGENT, then launch and check for its card in DECK.

**For DeepSeek / Local LLMs**: Complete [API setup](native-setup.md), then choose the configured Model and Harness in NEW AGENT at `http://127.0.0.1:8770/` and launch. When a card with the scientist's name appears in DECK, try the guide's short conversation check and the [Mail check below](#5-play-shiritori-as-an-end-to-end-check).

**For Claude Code / Codex**: Sign in to your chosen CLI in the same OS environment, then run:

```bash
agent-start ~/code/my-project          # for Codex CLI: agent-start-codex ~/code/my-project
```

On macOS, open the dashboard from another terminal. On Windows, paste the same URL into your Windows browser.

```bash
open http://127.0.0.1:8770/
```

**Claude/Codex success check**: Your chosen CLI starts and a card with a scientist's name appears in DECK, showing the model and remaining context.

### 4. Spawn one child

This is the delegation example for Claude Code / Codex. If you started with DeepSeek/Local, use the API guide's launch check and the [Mail check in the next section](#5-play-shiritori-as-an-end-to-end-check).

Inside the running agent, ask for a child. This is the same in Claude Code and Codex.

```text
/delegate create a child agent and have it answer with its name and today's date
```

**Success**: a second card appears on the dashboard with a line from the parent to the child. When the child finishes, a "done" message arrives in the parent's terminal. The NETWORK tab shows the messages passing between the two.

By default the child's OS terminal opens automatically in the background. If you watch children from the dashboard, set `AGENTSTACK_AUTO_OPEN_CHILD=0` to stop the extra windows and open only the child you need with Deck Open tmux (see [Configuration](telemetry-configuration.md#child-spawn)).

### 5. Play shiritori as an end-to-end check

For an unconfigured dsh / Hermes backend, first complete [API setup](native-setup.md), including the instructions for people without an existing agent. Start one agent from NEW AGENT and check its response to a short request. The Mail round trip below is an additional check once two agents are ready; it does not require you to install Claude/Codex or add the cockpit.

If you use both Claude Code and Codex, the following shiritori (Japanese word-chain) example checks name registration, ORRERY Mail round trips, notification injection and dashboard rendering together.

```text
/delegate spawn one Codex child and play shiritori with it. Use the installed ORRERY /delegate skill to create the child and ORRERY Mail (send_message) to communicate; pass these tool requirements to the child too. Do not use built-in Agent or SendMessage. Exchange one word per turn and report the result after ten round trips.
```

This standalone example uses ten round trips. [Workshop shiritori](https://github.com/gyroid-eth/orrery-workshop/blob/master/play/shiritori.md) and Full tour use three; the lecture uses that shorter version.

If you start from Codex, make the child a Claude Code agent. Either way, the point is to see the game go round between agents from two vendors.

The same shiritori check also works with DeepSeek or Local children in an environment with cockpit added and a configured provider and harness. In cockpit New Agent, select a [configured provider](telemetry-install.md) (DeepSeek or Local) and Harness (dsh or Hermes), select the Claude Code or Codex agent you will play with as the parent under Lineage, and create the child for three round trips.

With Telemetry alone, the bundled dashboard NEW AGENT also lets you select a provider, model and Harness (dsh or Hermes) marked available in the catalog. For a launch without the screen, use `POST /api/spawn` in the [API reference](https://github.com/gyroid-eth/orrery-telemetry/blob/master/docs/api.en.md), including its authentication and parent (parent or standalone) contract, and always specify `harness`.

Have the parent start by sending the child “Play three shiritori round trips over ORRERY Mail, putting each turn’s word in the subject of each Mail” using ORRERY Mail `send_message`. Success looks the same: lines flow back and forth in NETWORK, and the last instruction on both DECK cards updates to the latest Mail subject (that turn’s word). Check dsh and Hermes separately; success with one does not verify the other.

**Success**: lines keep flowing back and forth between the two agents in NETWORK, and the "last instruction" on both DECK cards updates word by word. On the author's machine each turn took about five to six seconds per agent ([post with video](https://x.com/i/status/2095650715008168255), played at double speed).

Once you are here, just use your agents as usual. See [Installation](telemetry-install.md) and [Configuration](telemetry-configuration.md) for settings, and [Delegation and child agents](delegation.md) for how children work.


## Bundled skills and screen references

`/delegate` hands a job to a child and receives its completion report. See [Delegation and child agents](delegation.md) for the difference from native subagents, and [Launcher skills](launchers.md#skills-2-and-file-reservations) for registration, reservations, and startup. Claude discovers the standard skill path; Codex learns the same playbook location from managed `~/.codex/AGENTS.md` instructions.

`/log` records decisions, changes, verification, and next actions as Markdown in `logs/`. [Launcher log](launchers.md#log) and [Obsidian setup](obsidian.md) explain storage and Daily Note links. Those logs appear under Output on the dashboard.

[Dashboard](dashboard.md) contains detailed controls and images for DECK, NETWORK, DIGEST REPLAY, and NEW AGENT. For terminals and telemetry in one screen, start with the in-app guides in [ORRERY cockpit](https://github.com/gyroid-eth/orrery). [Using it with Obsidian](obsidian.md) includes a moving example and the public demo vault.

## What runs underneath

- **ORRERY Mail**: one place for agent names, inboxes, and file reservations. It remains the source of truth even if the dashboard goes down.
- **Launchers**: `agent-start` registers the name, creates the tmux session, and starts the CLI in one step, so dashboard jumps and notification targets resolve to exactly one place.
- **Hooks**: Nine Claude event hooks stop unregistered sessions and unreserved writes, and inject arriving messages into the agent's prompt.

Details of these mechanisms and the API are in [Hooks](https://github.com/gyroid-eth/orrery-telemetry/blob/master/docs/hooks.en.md), [Launchers](launchers.md), and the [API reference](https://github.com/gyroid-eth/orrery-telemetry/blob/master/docs/api.en.md). Every dashboard view and control is available through the local HTTP API.


## How it fits together

```text
Claude Code / Codex CLI / dsh / Hermes
        │ launchers + hooks
        ▼
tmux session ── telemetry ──► dashboard
        │                         ▲
        │                         │ sanitized snapshot
        │                  Codex App Bridge ◄── plugin hooks ── Codex Desktop
        │                         │
        └──────── ORRERY Mail ◄────┘
                  identity / inbox / reservations
```

The bundled ORRERY Mail server is the source of truth, with launchers, operational guards, visualization, and a control plane layered on top. If the dashboard stops, identities, mail, and reservations remain in their source of truth.


## Supported environments

| Environment | Support |
| --- | --- |
| macOS | Supported |
| Windows (WSL2) | Supported. Verified on Windows 11 + Ubuntu 26.04 / WSL 2.7 from install through spawning a child and jumping to a terminal from the dashboard. Steps: [WSL2 section of the install guide](telemetry-install.md#installing-on-windows-wsl2) |
| Linux | Field reports received. On Ubuntu 24.04 / tmux 3.4, install, the dashboard, and Codex agents worked, and the two problems found there ([#26](https://github.com/gyroid-eth/orrery-telemetry/issues/26), [#27](https://github.com/gyroid-eth/orrery-telemetry/issues/27)) are fixed. The author has not verified `systemd --user` registration, so please report results as issues |
| Windows native (without WSL2) | The supported route is WSL2, but community contributions provide an experimental PowerShell helper that starts Mail and the dashboard, and a native Codex child launcher ([startup helper](windows-local.md), [Codex launcher](https://github.com/gyroid-eth/orrery-telemetry/blob/master/docs/windows-codex-launcher.en.md)). Policy: [#3](https://github.com/gyroid-eth/orrery-telemetry/issues/3) |

The table above covers the common infrastructure and existing CLI routes. DeepSeek / Local × dsh / Hermes use a separate legacy-mode route requiring backend, runtime and OS credential-reference configuration. Catalog visibility does not guarantee a successful connection: verify launch and Mail round trips for each configured combination.

Python 3.11 or newer, `git`, `tmux`, and `uv` are required. The CLI procedure above needs a signed-in Claude Code or Codex CLI; API spawning separately needs dsh / Hermes and backend configuration. The installer checks common dependencies before writing anything and stops without changes if something is missing. The details of the checks and the optional dependencies (`fswatch`, `fzf`, Ghostty, Obsidian) are in the [install guide's environment section](telemetry-install.md#supported-environment).


## Look before installing

The [public demo](https://agentstack-demo.pages.dev/) is a four-minute loop of the dashboard with scripted data and explanatory captions. It does not verify your own CLI, Mail, or delegation. The [“Orrery” introduction video](https://youtu.be/Jpc1ad7c90k) (about 90 seconds, English; [Japanese version](https://youtu.be/JXoa93TQolU) also available) illustrates the idea rather than recording the real screen.
