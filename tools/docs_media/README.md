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
