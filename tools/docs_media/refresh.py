#!/usr/bin/env python3
"""Regenerate the Cockpit and Telemetry documentation image set."""

from __future__ import annotations

import argparse
import contextlib
import os
import select
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path

from browser import camera
from guide_scenes import save_guides
from PIL import Image, ImageDraw
from scenes import save_cockpit, save_dashboard, save_phone


def snapshot(source, destination):
    destination.mkdir()
    commit = subprocess.check_output(
        ["git", "-C", source, "rev-parse", "HEAD"], text=True
    ).strip()
    with subprocess.Popen(
        ["git", "-C", source, "archive", commit], stdout=subprocess.PIPE
    ) as archive:
        subprocess.run(
            ["tar", "-x", "-C", destination], stdin=archive.stdout, check=True
        )
        if archive.wait():
            raise RuntimeError(f"git archive failed for {commit}")
    print(f"{source.name} {commit}", flush=True)


def chart(destination):
    image = Image.new("RGB", (440, 220), "#f4f0e8")
    draw = ImageDraw.Draw(image)
    draw.line([(32, 30), (32, 190), (412, 190)], fill="#4f5f65", width=2)
    draw.line(
        [(38, 165), (124, 138), (206, 150), (284, 98), (398, 55)],
        fill="#326991",
        width=5,
    )
    image.save(destination)


@contextlib.contextmanager
def fixtures(root, *, guide_board=None):
    command = [sys.executable, str(Path(__file__).with_name("fixture.py")), root]
    if guide_board is not None:
        command.extend(["--guide-board", guide_board])
    with subprocess.Popen(
        command, stdout=subprocess.PIPE, text=True, bufsize=1
    ) as process:
        try:
            # The private server announces the two OS-assigned loopback ports.
            ports = []
            while len(ports) < 2:
                if not ports and not select.select([process.stdout], [], [], 20)[0]:
                    raise RuntimeError("The documentation fixture did not start")
                line = process.stdout.readline().strip()
                if not line.isdecimal():
                    raise RuntimeError(
                        "The documentation fixture exited during startup"
                    )
                ports.append(int(line))
            if set(ports) & {8770, 8765, 8791, 9443}:
                raise RuntimeError("Fixture port overlaps with the live installation")
            yield tuple(f"http://127.0.0.1:{port}" for port in ports)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cockpit-source",
        type=Path,
        required=True,
        help="Checkout of the cockpit version to capture",
    )
    parser.add_argument(
        "--telemetry-source",
        type=Path,
        required=True,
        help="Checkout of the Telemetry version to capture",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Write assets below cockpit/ and telemetry/ here",
    )
    parser.add_argument(
        "--cdp", default=os.environ.get("ORRERY_CDP_URL", "http://127.0.0.1:9250")
    )
    parser.add_argument(
        "--group", choices=("all", "cockpit", "dashboard", "phone", "guides"), default="all"
    )
    parser.add_argument(
        "--guide-board", type=Path, help="Tracked task note from the public demo vault (required for --group guides)"
    )
    args = parser.parse_args()
    if args.group == "guides" and args.guide_board is None:
        parser.error("--group guides requires --guide-board")
    if urllib.parse.urlsplit(args.cdp).hostname not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        parser.error("--cdp must be a loopback Chrome debugging endpoint")
    with tempfile.TemporaryDirectory(prefix="orrery-docs-media-") as directory:
        root = Path(directory)
        snapshot(args.cockpit_source.resolve(), root / "app")
        snapshot(args.telemetry_source.resolve(), root / "tel")
        if args.group == "guides":
            with fixtures(root, guide_board=args.guide_board.resolve()) as (cockpit, _):
                with camera(args.cdp, (1320, 760)) as browser:
                    save_guides(browser, args.output / "cockpit", cockpit)
            return
        subprocess.run(
            [
                "bash",
                str(root / "tel/dashboard/demo/build.sh"),
                str(root / "demo"),
                "--enable-dsh",
            ],
            check=True,
        )
        chart(root / "sample-chart.png")
        staged = root / "staged"
        with fixtures(root) as (cockpit, phone):
            if args.group in {"all", "cockpit"}:
                with camera(args.cdp, (1488, 900)) as browser:
                    save_cockpit(browser, staged / "cockpit", cockpit)
            if args.group in {"all", "dashboard"}:
                with camera(args.cdp, (1920, 1080)) as browser:
                    save_dashboard(browser, staged / "telemetry", cockpit)
            if args.group in {"all", "phone"}:
                with camera(args.cdp, (412, 915), phone=True) as browser:
                    save_phone(browser, staged / "telemetry", phone)
        shutil.copytree(staged, args.output, dirs_exist_ok=True)


if __name__ == "__main__":
    main()
