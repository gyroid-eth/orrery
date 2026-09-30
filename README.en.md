# ORRERY

> Japanese is the source of truth: [日本語版 (README.md)](README.md)

<img src="app/icons-src/orrery-1024.png" alt="ORRERY icon" width="96">

ORRERY is a cockpit for people who run several Claude Code / Codex agents as a team. You do not have to hunt from window to window for the agent that is waiting for your reply. However many agents you run, only the ones waiting for a human decision blink in the roster so you can spot them at a glance, and you see every terminal, the traffic between agents, and your remaining usage quota on one screen while sending instructions from the same place. It runs on Mac (`ORRERY.app` and a browser) and on Windows (WSL2 and a browser), and works with [ORRERY Telemetry](https://github.com/gyroid-eth/orrery-telemetry).

![The whole ORRERY cockpit. On the left, the agent roster; in the center, a Split with three terminals side by side; at the top right, the mini-orrery drawing the parent–child tree; at the bottom right, the ORRERY Mail list](docs/images/cockpit_overview.png)

Pick an agent in the roster on the left, give instructions in the terminal in the center, and follow parent–child relationships and messages in the mini-orrery and Mail on the right. The terminals work even when ORRERY Telemetry is not running; features that depend on it show their status and degrade gracefully.

**Introduction video**: "Orrery" (90 s) is an illustrated explainer of the idea behind ORRERY: agents talk to each other directly, so you no longer relay between AIs. It does not show the actual screens. A [Japanese version](https://youtu.be/JXoa93TQolU) is also available.

[![Introduction video "Orrery" (YouTube)](https://i.ytimg.com/vi/Jpc1ad7c90k/hqdefault.jpg)](https://youtu.be/Jpc1ad7c90k)

## What you can do

### Your half-typed message is not swept away

When many agents run at once, notifications from other agents can pour into the same terminal while you are typing an instruction to a parent agent, burying what you have written so far. In the cockpit you type instructions into a separate input box (the composer) below the terminal, so whatever scrolls through the terminal, your draft stays put. To change the recipient, just click an agent in the roster or on a tab; the text carries over.

![While a message for CoralCurie is being typed in the composer, three Mail notifications flow into the terminal. The draft stays; clicking OnyxDarwin in the roster changes the recipient, and OnyxDarwin receives the message when it is sent](docs/images/cockpit_composer_calm.gif)

→ [Usage: Prompt composer](docs/en/usage.md#prompt-composer)

### Spot the agents that need a human decision at a glance

However many agents you run, only the agents whose work has stopped while they wait for a human decision light up in the roster (an approval wait blinks red, a question wait pulses slowly in light blue), and `N need you` appears in the header. Press `need you` to narrow the roster to just those agents, click a tile to enter its terminal and read the question. Send your answer from the composer and the blinking stops. You can clear the stopped agents in the order they stopped, without hunting for them.

![Among 7 agents, only PearlFaraday blinks red and 1 need you appears in the header. Narrowing with need you, clicking the tile to read the approval question, and sending 1 from the composer makes the blinking stop](docs/images/cockpit_need_you.gif)

The same holds in TELEMETRY: a question wait is shown by `?`, and an approval wait by a red frame and `APPROVAL`.

<img src="docs/images/deck_humanloop.png" alt="The TELEMETRY DECK. A question wait is shown with a question mark; an approval wait with a red frame and APPROVAL" width="480">

→ [Usage: Agents that need a human decision](docs/en/usage.md#agents-that-need-a-human-decision) · [Spotting agents that need you (TELEMETRY)](docs/en/usage.md#spotting-agents-that-need-you)

### Read what agents are saying to each other, right where you are

Agents ask, report, and point things out to each other through ORRERY Mail. That Mail streams down the rail on the right, newest first, so you can read the team's conversation without opening each terminal one by one. Click a card to read the body, or press `thread` to open the back-and-forth of that conversation in time order. Selecting an agent in the roster narrows the list to only the Mail that agent is involved in.

![Two new Mails flow in and lines of traffic run across the mini-orrery. Clicking a card to read the body, reading a 4-message back-and-forth in time order with thread, and selecting PearlFaraday in the roster narrows the list to just that agent's Mail](docs/images/cockpit_mail.gif)

→ [Usage: Agent Mail](docs/en/usage.md#agent-mail)

### Pin the agents you watch most to the top (Pin)

With many agents running, the roster keeps reordering by state (approval wait, working, idle). Pin the agents you always look at, such as a parent agent or a reviewer, and they stay at the very top regardless of reordering, grouped above a divider line. Just hover over a tile and press the pin at its upper right; press it again to unpin. Pins are shared between ORRERY.app and browser tabs, and an agent is unpinned automatically when it retires (pins exist only in the roster on the left).

![While the roster of 7 agents reorders as states change, pinning JadeNoether moves it to the top and draws a divider, and it stays on top while other agents reorder. Pressing it again unpins it and it returns to its original position](docs/images/cockpit_pin.gif)

→ [Usage: Pin](docs/en/usage.md#pin)

### Put several terminals side by side (Split)

Hold `Cmd` / `Ctrl` while selecting agents to line up to 12 terminals on one screen. Drag a name tag to swap positions, and drag a border to change widths. You can watch a parent agent and the progress of its children at the same time.

![In a Split with three agents, dragging name tags to swap them and dragging a border to change widths](docs/images/cockpit_split_drag.gif)

→ [Usage: Split](docs/en/usage.md#split)

### Take one terminal out (standalone window)

Drag a tab's name tag onto the terminal to make it a small window floating above the cockpit (`FLOAT`). Drag it out of the cockpit, or press `↗`, and it becomes a standalone window (`WINDOW`) that you can place on another monitor and view larger. Close the window and it returns to its tab. It works in ORRERY.app and in browsers on Mac and WSL.

![Dragging a name tag to float it, moving it, turning it into a standalone window with ↗, and closing it to return it to a tab](docs/images/cockpit_pane_float.gif)

![JadeNoether floating above the cockpit, and CoralCurie open in a standalone window](docs/images/cockpit_pane_window.png)

→ [Usage: Standalone window](docs/en/usage.md#standalone-window)

### Open from the terminal, hand to the terminal

A URL an agent prints in the terminal opens in your default browser when clicked, and a file path opens in Finder (File Explorer on Windows). In the other direction, paste a file you copied in Finder (File Explorer on Windows) into the composer and its absolute path is inserted, ready to hand to the agent. Paste a screenshot and, on Mac, the agent's CLI receives it as is; on Windows (WSL2), the image is saved and its path is inserted.

![Clicking a URL in the terminal to open it in the browser, clicking a path to reveal it in Finder, and pasting a file into the composer to insert its path](docs/images/cockpit_open_paste.gif)

→ [Usage: Open from and hand to the terminal](docs/en/usage.md#open-from-and-hand-to-the-terminal) · [Pasting files and images on WSL](docs/en/usage.md#pasting-files-and-images-on-wsl)

### A light color scheme (light mode)

In Settings, Color theme switches between a dark scheme (Dark) and a paper-like light scheme (Light). Colors inside the terminal and the embedded TELEMETRY change with it, and text is adjusted to stay readable even on the red and green backgrounds of a diff. `System` follows your OS appearance.

![Changing Color theme in Settings to Light, then back to Dark](docs/images/cockpit_theme_switch.gif)

→ [Usage: Color theme (light mode)](docs/en/usage.md#color-theme-light-mode)

### See how much quota is left (Usage)

`LEFT` in the header shows what percentage of your Claude and Codex account quota remains. Click it to see the 5-hour window, the weekly window, and per-model windows, each with the time until reset. The numbers change between green, yellow, and red, and when a value cannot be fetched, the reason is shown.

![Clicking LEFT in the header opens Usage left, with the remaining quota for each Claude and Codex window drawn as arcs. As the remaining amount decreases, the numbers and rings change from green to yellow to red](docs/images/cockpit_usage.gif)

→ [Usage: Usage (remaining quota)](docs/en/usage.md#usage-remaining-quota)

### Copy a name, see the details (Roster)

Hover over a roster tile to show a copy icon. A copied name can be pasted straight into a Mail recipient or an instruction. The detail card of a tile lists the last time the agent was active and the number of its deliverables.

![Roster tiles. The copy icon and the detail card](docs/images/cockpit_roster_pin_copy.png)

→ [Usage: Roster](docs/en/usage.md#roster)

### See parent–child relationships and traffic (Planetarium)

`PLANETARIUM` in the header opens, full screen, a tree of who launched whom. A line lights up between any two agents that exchanged Mail in the last 90 seconds, and a comet flies each time Mail arrives, so you can see at a glance where in the team conversations are happening. Click a node to jump straight to that agent's terminal.

![Pressing PLANETARIUM opens a tree with CoralCurie as the parent of 6 children, and lines light up each time Mail arrives. Clicking JadeNoether's node jumps to its terminal](docs/images/cockpit_planetarium.gif)

→ [Usage: Planetarium](docs/en/usage.md#planetarium)

### See the state of the whole team (TELEMETRY)

`TELEMETRY` in the header opens the ORRERY Telemetry dashboard inside the cockpit. `DECK` shows one card per agent, and `NETWORK` shows the connections between agents as nodes and lines; select an agent to read its conversation and tool history and the list of its deliverables. Press `OPEN IN COCKPIT` to return straight to that agent's terminal. Without going to another screen, you can survey the whole team inside the cockpit and go right back to the terminal at hand. Resuming finished agents is also done here.

![Pressing TELEMETRY in the header opens the DECK inside the cockpit; switching to NETWORK and selecting JadeNoether, looking at its history, then returning to JadeNoether's terminal with OPEN IN COCKPIT](docs/images/cockpit_telemetry.gif)

**REPLAY**: After the work is done, you can review what the team did and in what order, like a recording. Press `SELECT` in NETWORK, choose agents, and press `Replay`; the history of the chosen agents plays out along a time axis, and who launched whom (spawn) and what Mail they sent each other appear in order, with subjects. Fast-forward with the speed scale, and click the time axis below to jump to any moment.

![Selecting 7 agents in NETWORK and pressing Replay starts with only the parent CoralCurie; children appear one by one through spawn, and Mail subjects flow by as speech bubbles. Raising the speed and jumping to the later part of the time axis shows everyone connected](docs/images/cockpit_replay.gif)

→ [Usage: TELEMETRY](docs/en/usage.md#telemetry)

### Use it together with Obsidian

When you run agents inside an Obsidian vault, work logs, paper notes, and tasks become Markdown notes as they are, and all a person has to do is look at them in Obsidian's Daily Note and Kanban. A note path that an agent prints in the terminal opens when you click it in the cockpit. ORRERY works without Obsidian; this is just one convenient way to use it.

![Typing /adddone review the paper note to Claude on WSL makes that task disappear from "Tasks" and appear under "Done today" in the Obsidian Daily Note on the right](docs/images/cockpit_obsidian.gif)

→ [Use it together with Obsidian](https://github.com/gyroid-eth/orrery-telemetry/blob/master/docs/obsidian.en.md) (an ORRERY Telemetry document) · a template you can try right away, [orrery-demo-vault](https://github.com/gyroid-eth/orrery-demo-vault)

Reading notes for papers come from the add-on [orrery-digest-paper](https://github.com/gyroid-eth/orrery-digest-paper): Claude writes the note, and Codex checks it against the text and the figures (a version for Zotero users is included).

### The same screen on Windows (WSL2)

Run the backend in WSL2 and open it in a Windows browser to use the same screen as on Mac. Shortcuts change to `Alt+K` and so on, the terminal opened externally becomes Windows Terminal, and links open in the Windows browser and File Explorer. Files copied in File Explorer and screenshots can also be handed to the agent as paths by pasting them into the composer.

![The Jump palette opened on WSL. Alt+K is shown at the top left](docs/images/cockpit_palette_wsl.png)

→ [Usage: Differences on Windows (WSL2)](docs/en/usage.md#differences-on-windows-wsl2)

### And more

- Search agents and tmux sessions and jump to their terminals (`Cmd+K`; `Alt+K` on WSL)
- Send from the composer. Send history, suggestions for skills and commands with `/` or `$`, and a send guard that stops commands that would delete a session, or mistyped symbols, before they are sent ([Prompt composer](docs/en/usage.md#prompt-composer))
- NEW AGENT and bulk EXIT of ORRERY Telemetry from the cockpit ([NEW AGENT](docs/en/usage.md#new-agent))
- Adjusting small text and letter spacing (Vision profile; [Color theme](docs/en/usage.md#color-theme-light-mode))

## Requirements

- macOS, or Windows with WSL2 (Ubuntu). `ORRERY.app`, the installer, and the global hotkey are macOS only
- Python 3.10 or later, and `tmux`
- Node.js / npm and Rust / Cargo (to develop or build the desktop app)
- A running [ORRERY Telemetry](https://github.com/gyroid-eth/orrery-telemetry) (to use all integrated features)
- ORRERY Mail SQLite (to use the mail rail)
- Access to a runtime CDN (for `xterm.js` and its addons; the current distribution is not a fully offline bundle)

See [Installation](docs/en/install.md) for details and requirements by role.

## Quick start

**If this is your first install, the steps in [Installation, "For first-time installers"](docs/en/install.md#for-first-time-installers-browser-mac--windows-wsl2) are all you need.** After installing ORRERY Telemetry, run `./scripts/start-cockpit.sh` and open the URL it prints in a browser (Mac and Windows WSL2). What follows is the procedure for setting things up by hand.

```bash
git clone https://github.com/gyroid-eth/orrery.git
cd orrery

python3 -m venv bridge/.venv
bridge/.venv/bin/python -m pip install -r bridge/requirements.txt
```

Start the ORRERY Telemetry dashboard at its default `http://127.0.0.1:8770`, and give ORRERY the same project key and mail DB.

```bash
export AGENTSTACK_PROJECT_KEY=/absolute/path/to/your/project
export ORRERY_PROJECT_KEY="$AGENTSTACK_PROJECT_KEY"
# Only if you use a DB other than the default:
# export ORRERY_MAIL_DB=/absolute/path/to/storage.sqlite3
```

First check the connection with the backend and a browser.

```bash
bridge/.venv/bin/python bridge/orrery_backend.py
open http://127.0.0.1:8791/cockpit.html
```

To build the desktop app:

```bash
cd app
npm ci
npm run build
```

The output is `app/src-tauri/target/release/bundle/macos/ORRERY.app`. The current `.app` is a sidecar setup that uses the checkout and the already-built `bridge/.venv`; it does not bundle the backend. When launched from Finder, it resolves the sidecar from `orrery_root` in `~/.orrery/config.json`. See [Installation](docs/en/install.md#set-the-sidecar-path) and [Configuration](docs/en/configuration.md#shared-settings-file) for details.

## Your first 30 minutes

Once the clone and venv are ready, follow this single path to confirm that you can find agents, operate them, add more, and observe their conversations. If what you see differs at any step, do not go on; use [Troubleshooting](docs/en/troubleshooting.md) to isolate that step.

1. **Check the connection between the backend and ORRERY Telemetry.** Start the ORRERY Telemetry dashboard on `127.0.0.1:8770` and the ORRERY backend on `127.0.0.1:8791`, and open `http://127.0.0.1:8791/telemetry/health` in a browser. **Success:** `backend` is `ok`, and if you are using all integrated features, `dashboard` is also `true`.
2. **Check that agents appear in the cockpit.** Open `http://127.0.0.1:8791/cockpit.html`. **Success:** the header shows `live`, and the left roster lists running agents with their name, model, role, and context usage.
3. **Open an agent's terminal and do one round trip.** Click an agent in the roster, type a short test message into the prompt composer in the center, and press `Enter`. **Success:** a session tab and terminal for that agent open, and the agent's reply appears in the terminal after your message. Agents without a tmux pane, such as those from Codex App, are opened from TELEMETRY instead of in this step.
4. **Spawn one more agent.** Open `+ NEW AGENT`, choose the provider / model, the launch directory, and the required task, and press `Spawn`. Leaving it as `standalone` is fine at first. **Success:** after the `SPAWNED` toast, the new agent appears in the roster. If the catalog is visible but spawning fails, check the connection to the ORRERY Telemetry dashboard.
5. **Operate two agents side by side.** Hold `Cmd` (macOS) or `Ctrl` and click the roster tiles of the first agent and the second agent in turn. **Success:** the center becomes `SPLIT 2`, and the terminals of both sessions are visible at once.
6. **Watch the traffic between agents.** When ORRERY Mail passes between the two, click the new mail card on the right rail and open the body or thread. The comets and edges of the mini-orrery also show the last 90 seconds of traffic. **Success:** the sender, recipient, subject, and body are readable, and the mini-orrery reflects the spawn lineage and recent traffic.

With everything connected up to here, opening `TELEMETRY` shows the added agents and their traffic as below. This is not the ORRERY cockpit itself but a real `DECK` screen of the ORRERY Telemetry dashboard embedded in ORRERY. The image is a demo that grew to 12 agents; the number of agents and their content vary by environment.

![The TELEMETRY DECK embedded in ORRERY. Twelve agents lined up as cards](docs/images/deck_growing.png)

What to look for: if the `RUNNING` / `AGENTS` counts at the top, each card's task, and the `RX` on cards with traffic line up for your own environment, you are observing the telemetry of several agents together.

To find an operation starting from what you want to do, go to [Usage, "Find what you want to do"](docs/en/usage.md#find-what-you-want-to-do).

## Documentation

The Japanese documents are the source of truth. The English versions are in README.en.md and `docs/en/`, and every document in this table has an English version.

| Document | Contents |
| --- | --- |
| [Installation](docs/en/install.md) | Requirements, venv, connecting to ORRERY Telemetry, the backend, `ORRERY.app` |
| [Configuration](docs/en/configuration.md) | All environment variables, defaults, connection targets and storage locations |
| [Usage](docs/en/usage.md) | Roster, terminal, split, spawn, mail, TELEMETRY, replay |
| [Troubleshooting](docs/en/troubleshooting.md) | Startup, ports, `:8770`, `pyte`, tmux, CDN |
| [Architecture overview](docs/en/ARCHITECTURE_OVERVIEW.md) | tmux, Codex App, network, data retention, handling of portrait images |
| [Implementation architecture](docs/en/ARCHITECTURE.md) | Details of the backend, HTTP / WebSocket, and tmux control |
| [Design language](docs/en/DESIGN.md) | The cockpit's visuals, motion, color, and typography |

## Structure

```text
ORRERY.app / browser
        │ HTTP + WebSocket (:8791)
        ▼
ORRERY Python backend
  ├─ tmux control mode ── local agent sessions
  ├─ read-only SQLite ─── ORRERY Mail
  └─ HTTP proxy ───────── ORRERY Telemetry dashboard (:8770)
```

The ORRERY backend does not import ORRERY Telemetry's `server.py`; it works with it through an HTTP proxy and its own tmux / mail / portrait handlers. Terminal input, window size claims, spawn, and EXIT change state. It is not a mere read-only viewer.

## Security and privacy

The backend binds only to `127.0.0.1` and refuses external binds. However, there is no authentication on localhost, so do not run it in an environment with untrusted local processes.

The terminal recorder saves history to `~/.orrery/history` by default, and prompt drafts and up to 50 sent messages remain in the browser's `localStorage`. If you enter confidential information, check the storage locations and retention policy in [Configuration](docs/en/configuration.md#stored-data-and-privacy).

## Third-party components

ORRERY works with ORRERY Telemetry, `tmux`, `xterm.js`, and others. This repository does not contain ORRERY Mail code. For ORRERY Mail's license and third-party notices, see [ORRERY Telemetry](https://github.com/gyroid-eth/orrery-telemetry).

The portrait images in `assets/portraits/` and `assets/portraits_64/` are outside the PolyForm Perimeter License. The license of each image (public domain, CC0, CC BY 4.0, CC BY-SA 2.0 / 4.0), its author, source, and the processing applied follow [CREDITS.md](CREDITS.md). Processed CC BY-SA images are also provided under the same CC BY-SA. A portrait that is not in the manifest / CREDITS is not treated as an asset approved for distribution. However, the 50 pixel-art portraits in `assets/portraits_px/` were generated by the author, gyroid, with ChatGPT (OpenAI image generation) from text instructions alone. No photographs were used as input. They are distributed under the same terms as the repository (PolyForm Perimeter License 1.0.1).

## License

This repository is under the **PolyForm Perimeter License 1.0.1** (except the portrait images; see [Third-party components](#third-party-components)). It is source-available, not open source in the OSI sense. See [LICENSE](LICENSE) for the full text. © 2026 gyroid.

- You may use, modify, and redistribute it for any purpose
- However, you may **not offer a product that competes with this software to others**. Free distribution, porting to another language, and offering it as a service / library / plug-in also count as competing
- It comes with no warranty. No support is promised

## Reporting problems

Report problems in the GitHub repository's Issues. Including the task name, the steps to reproduce, the startup logs of ORRERY / ORRERY Telemetry, and the result of `/telemetry/health` will speed up isolating the cause.
