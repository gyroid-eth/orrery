# Documentation index

[日本語](../README.md) · [README](../../README.en.md)

Start with **Your first flight → help map → Full tour** on screen, from cockpit’s `Settings → Getting started`. This index is for install/update, troubleshooting, and detailed references when you need them.

## Start here

- [Quick start](../../README.en.md#quick-start) — Install the base and continue to the first-flight guide.
- [Installation](install.md) — Check the one-line installer prerequisites, plan, and results, then open cockpit.
- [Research set](research-set.md) — Add digest-paper and a public demo vault after the base installation.

## Use the screen

- [Usage](usage.md) — Start with in-app guides and help map; look up detailed controls as needed.
- [Full tour](../FULL_TOUR.md) — Sixteen real interactions, completion checks, the game, progress, and pop-out window.

## Install and update

- [Update](install.md#5-update) — Update while keeping existing settings.
- [Configuration](configuration.md) — Look up connections, environment variables, storage, and privacy settings.

## Windows and WSL

- [WSL2](install.md#for-first-time-installers-browser-mac--windows-wsl2) — Install inside Ubuntu for the standard Windows route; open it in a Windows browser.
- [Windows UI](usage.md#differences-on-windows-wsl2) — Shortcuts, Windows Terminal, and file/image handling.

## Troubleshoot

- [Troubleshooting](troubleshooting.md) — Isolate startup, connection, port, tmux, and CDN problems.

## Design and development

- [Architecture overview](ARCHITECTURE_OVERVIEW.md) — tmux, Codex App, network, history, and portrait boundaries.
- [Implementation architecture](ARCHITECTURE.md) — Read backend HTTP/WebSocket, tmux control, and Mail integration.
- [Design language](DESIGN.md) — The implementation reference for visuals, motion, color, and typography.
- [Roster findability design (discussion draft)](DESIGN_roster_findability.md) — Historical measurements and proposals, distinct from current operating instructions.
- [Development entry](../../app/README.md) — Build, validation, and contribution procedures.

Documents without a translation are labelled with their original language. Images/GIFs accompany their articles. From the repository root, run `python3 scripts/check_docs_index.py` to check index coverage.
