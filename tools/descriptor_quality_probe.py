#!/usr/bin/env python3
"""Measure how much task content remains after relay boilerplate is removed.

This is a read-only design probe, not the production descriptor classifier.
Its constants are deliberately explicit so the 2026-08-06 measurement can be
reproduced and challenged against other populations.

Examples:
    python3 tools/descriptor_quality_probe.py
    python3 tools/descriptor_quality_probe.py --json agents.json
    python3 tools/descriptor_quality_probe.py --json agents.json \
        --population non-running --list generic
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterable


DEFAULT_URL = "http://127.0.0.1:8791/telemetry/agents"
DEFAULT_TIMEOUT_SECONDS = 5.0
SPECIFIC_SIGNAL_THRESHOLD = 4
MIN_AGENT_NAME_STRIP_CHARS = 4

# Long phrases come first. These are the exact English relay terms used for
# the 2026-08-06 36-agent probe; do not silently expand this list after seeing
# holdout errors, because that would erase the value of the holdout.
RELAY_ENGLISH = (
    "read and execute",
    "task execution",
    "parent-agent",
    "mcp agent mail",
    "canonical",
    "inbox",
    "awaiting",
    "execute",
    "execution",
    "read",
    "task",
    "delivered",
    "received",
    "delegated",
    "assigned",
    "parent",
    "agent",
    "mail",
    "under",
    "from",
    "via",
    "for",
    "by",
    "the",
    "in",
    "of",
    "and",
    "it",
)

RELAY_JAPANESE = (
    "親エージェント",
    "正本タスク",
    "委任された",
    "実行する",
    "対応する",
    "受け渡し",
    "からの",
    "親側",
    "正本",
    "タスク",
    "依頼",
    "受信",
    "届いた",
    "届く",
    "経由",
    "委任",
    "実行",
    "対応",
    "待機",
    "本人",
    "から",
    "への",
    "親",
    "へ",
    "の",
    "を",
    "で",
)

SESSION_PATH_RE = re.compile(
    r"(?:^|\s)(?:codex|claude(?: code)?)\s+session\s+in\s+(?:/|~)\S*",
    re.IGNORECASE,
)
ABSOLUTE_PATH_RE = re.compile(r"/(?:users|home|tmp|private)/\S*", re.IGNORECASE)
COORDINATION_TICKET_RE = re.compile(
    r"\b(?:pr|ticket|issue)-[a-z0-9_-]+\b", re.IGNORECASE
)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json",
        type=Path,
        metavar="FILE",
        help="read a saved telemetry JSON payload instead of the default URL",
    )
    parser.add_argument(
        "--population",
        choices=("roster", "running", "non-running", "all"),
        default="roster",
        help=(
            "agents to classify: roster matches cockpit.html; running tests "
            "running=true; non-running is the holdout; all disables filtering "
            "(default: roster)"
        ),
    )
    parser.add_argument(
        "--list",
        dest="list_quality",
        choices=("specific", "generic", "missing", "all"),
        help="list matching agent names, signal residue, and task text",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help=f"telemetry URL used when --json is omitted (default: {DEFAULT_URL})",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"URL timeout in seconds (default: {DEFAULT_TIMEOUT_SECONDS:g})",
    )
    return parser.parse_args(argv)


def load_payload(args: argparse.Namespace) -> tuple[str, dict[str, Any]]:
    if args.json:
        source = str(args.json.resolve())
        try:
            with args.json.open(encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError(f"cannot read telemetry JSON {source}: {error}") from error
    else:
        source = args.url
        try:
            with urllib.request.urlopen(args.url, timeout=args.timeout) as response:
                payload = json.load(response)
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
            raise RuntimeError(f"cannot read telemetry URL {args.url}: {error}") from error

    if not isinstance(payload, dict) or not isinstance(payload.get("agents"), list):
        raise RuntimeError("telemetry payload must be an object with an agents array")
    return source, payload


def select_population(agents: Iterable[dict[str, Any]], population: str) -> list[dict[str, Any]]:
    if population == "all":
        return list(agents)
    if population == "running":
        return [agent for agent in agents if bool(agent.get("running"))]
    if population == "non-running":
        return [agent for agent in agents if not bool(agent.get("running"))]
    return [
        agent
        for agent in agents
        if (bool(agent.get("running")) or agent.get("category") == "agent")
        and agent.get("category") != "warmup"
    ]


def strip_word(text: str, word: str) -> str:
    return re.sub(rf"\b{re.escape(word)}\b", " ", text, flags=re.IGNORECASE)


def signal_only(text: str) -> str:
    return "".join(
        character
        for character in text
        if not character.isspace()
        and unicodedata.category(character)[0] not in {"P", "S"}
    )


def classify(task: Any, known_agent_names: Iterable[str]) -> dict[str, Any]:
    source = unicodedata.normalize("NFKC", str(task or "")).strip()
    if not source:
        return {"quality": "missing", "residue": "", "signal_chars": 0}

    residue = source.lower()
    residue = SESSION_PATH_RE.sub(" ", residue)
    residue = ABSOLUTE_PATH_RE.sub(" ", residue)
    for name in known_agent_names:
        residue = re.sub(re.escape(name), " ", residue, flags=re.IGNORECASE)
    residue = COORDINATION_TICKET_RE.sub(" ", residue)
    for word in RELAY_ENGLISH:
        residue = strip_word(residue, word)
    for word in RELAY_JAPANESE:
        residue = residue.replace(word, " ")

    residue = signal_only(residue)
    signal_chars = len(residue)
    quality = "specific" if signal_chars >= SPECIFIC_SIGNAL_THRESHOLD else "generic"
    return {"quality": quality, "residue": residue, "signal_chars": signal_chars}


def percentage(count: int, total: int) -> str:
    return "0.0%" if not total else f"{count / total * 100:.1f}%"


def compact_task(task: Any) -> str:
    return " ".join(str(task or "").split())


def run(args: argparse.Namespace) -> int:
    source, payload = load_payload(args)
    all_agents = [agent for agent in payload["agents"] if isinstance(agent, dict)]
    selected = select_population(all_agents, args.population)
    known_names = sorted(
        {
            str(agent.get("name") or "").lower()
            for agent in all_agents
            if len(str(agent.get("name") or "").strip()) >= MIN_AGENT_NAME_STRIP_CHARS
        },
        key=len,
        reverse=True,
    )

    rows = []
    for agent in selected:
        result = classify(agent.get("task"), known_names)
        rows.append(
            {
                "name": str(agent.get("name") or "<unnamed>"),
                "task": compact_task(agent.get("task")),
                **result,
            }
        )

    counts = {quality: 0 for quality in ("specific", "generic", "missing")}
    for row in rows:
        counts[row["quality"]] += 1

    total = len(rows)
    print(f"source: {source}")
    print(f"population: {args.population}")
    print(f"threshold: {SPECIFIC_SIGNAL_THRESHOLD} signal characters")
    print(f"total: {total}")
    for quality in ("specific", "generic", "missing"):
        print(f"{quality}: {counts[quality]} ({percentage(counts[quality], total)})")

    if args.list_quality:
        wanted = rows if args.list_quality == "all" else [
            row for row in rows if row["quality"] == args.list_quality
        ]
        print(f"\n{args.list_quality} rows: {len(wanted)}")
        for row in sorted(wanted, key=lambda item: item["name"].casefold()):
            residue = json.dumps(row["residue"], ensure_ascii=False)
            task = json.dumps(row["task"], ensure_ascii=False)
            print(
                f"{row['name']}\tquality={row['quality']}\t"
                f"signal={row['signal_chars']}\tresidue={residue}\ttask={task}"
            )
    return 0


def main() -> int:
    try:
        return run(parse_args(sys.argv[1:]))
    except RuntimeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
