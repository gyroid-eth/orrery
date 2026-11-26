# Capture documentation images

Run this command with Python 3.11 or later, `aiohttp`, `Pillow`, `websockets` 14 or later, Git, Bash, and Node. Use a running Chrome CDP endpoint on loopback. The ORRERY cockpit bridge's development virtual environment may already have the Python dependencies.

```sh
python3 tools/docs_media/refresh.py \
  --cockpit-source /path/to/orrery-checkout \
  --telemetry-source /path/to/orrery-telemetry-checkout \
  --output /path/to/captures
```

The command prints the two HEAD commits and exports their tracked files into a temporary directory. It uses two OS-assigned loopback ports and an isolated CDP browser context per surface. Cockpit and phone run with Demo mode and fictional data. Dashboard uses its demo build and the public reel fixture. The fixtures acknowledge actions locally so the capture can show the existing UI through completion. They do not run a CLI, a terminal process, or a Mail service.

From Telemetry, run `python3 scripts/refresh-docs-media.py` with the same flags. If the cockpit capture tool lives in a different checkout from the cockpit version you want to capture, add `--cockpit-tools /path/to/tool-checkout`.

The output contains `cockpit/docs/` and `telemetry/docs/`. Open the images and review the GIF frames before copying them to a documentation checkout. The two Codex `/hooks` illustrations require manual capture in an isolated Codex environment with a human reviewing approval.

Pass `--group cockpit`, `--group dashboard`, or `--group phone` to iterate on a single surface. The default CDP endpoint is `http://127.0.0.1:9250`. Set `ORRERY_CDP_URL` or pass `--cdp` for a different loopback endpoint.

## Cockpit task guides

Use the public demo vault's task note to capture the guides and the numbered
cockpit map. Both languages use the same control demonstrations. The Reader
and team clips have separate recordings for each language.

```sh
git -C /path/to/orrery-demo-vault show '1e10555:01_Planning/タスク.md' > /tmp/タスク.md
python3 tools/docs_media/refresh.py \
  --cockpit-source /path/to/orrery-checkout \
  --telemetry-source /path/to/orrery-telemetry-checkout \
  --guide-board /tmp/タスク.md \
  --output /path/to/captures \
  --group guides
```

Use Pillow 10.1 or later and have Poppler's `pdftoppm` available for environments
where Chrome cannot capture an individual still. The Mail clip records the
real cockpit's motion while an isolated fixture provides fictional messages.

Review each frame before copying the output from `cockpit/docs/images/guides/`.
These clips prioritize the relevant controls, so their crop changes as the
task moves from the New agent dialog to the composer or Reader. The cockpit map
is the full-screen exception. Keep its marker order and both map legends in sync.

The numbered map and task clips use the cockpit checkout. The Telemetry clip
also builds the Telemetry demo into the same private fixture. Copy
`cockpit/docs/images/cockpit_roster_detail.png` when refreshing the Roster
permissions illustration in the usage guide.

## Shared with Telemetry

| Cockpit asset | Telemetry reference |
| --- | --- |
| `docs/images/cockpit_telemetry_relation.svg` | Telemetry's `README.md`, `README.en.md`, `docs/README.md`, and `docs/README.en.md` embed the ORRERY raw URL. |
| `docs/images/deck_start.png`, `net_growing.png`, `net_humanloop.png`, `net_start.png` | Telemetry has byte-identical files in `docs/images/`. They are currently unlinked in both repositories. |
| `docs/images/deck_growing.png` and `docs/images/deck_humanloop.png` | Telemetry's Japanese and English dashboard guides use files with the same names and different contents. |

Review and replace the Telemetry-side assets in a separate Telemetry change.

## README feature clips

Run the cockpit task-guide command above with `--group hero` to capture
`team-hero.gif` and `team-hero.en.gif`. Install `gifsicle` for lossless frame
optimization within the 3 MB limit. The fixture starts with one agent. Submitting the typed
request makes four fictional child agents available in the roster and graph.
The script records their staggered Mail arrivals and scrolls Reader to the
parent's summary of the public demo vault task board. It uses fixed crops
during the moving shots. Review the five-agent roster, the comet subjects,
and all four rows of the final table before copying the file.

Use `--group reader` to record `read-a-file.gif` and `read-a-file.en.gif` from
the same task board. The full center pane stays in view as the terminal
streams output, Reader displays the grouped tools and table, and a reference
chip opens a Markdown preview before returning to the conversation.

Use `--group permissions` to capture `permission-switch.gif` on its own. Start
with the Mini Graph card open and both permissions Off. The clip frames the
card and native confirmations at readable size, with a strip from the Agents
list during the restart. It records Control and then Temporary Chrome. Install
`gifsicle` for lossless optimization of the GIF.

The regular `--group guides` run also captures this clip and
`select-agents.gif` through the exit animation.

Run the same command with `--group readme-phone` for `mobile.gif` and
`mobile-ipad.png`. This group can omit `--guide-board`. It uses the real
Telemetry phone page at 390 px with the isolated relay fixture, then checks
the side-by-side tablet layout at 820 px. Review the roster selection, typed
characters, confirmation, and send receipt. The fixture has no Tailscale
service and uses no real browser profile, agent process, or Mail.
