#!/usr/bin/env python3
"""Fail when the production JS classifier drifts from the Python probe."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from descriptor_quality_probe import MIN_AGENT_NAME_STRIP_CHARS, classify


HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "descriptor_telemetry_2026-08-06.json"
JS_TEST = HERE / "descriptor_quality_js_test.js"


class DescriptorQualityParityTest(unittest.TestCase):
    def test_python_and_javascript_classify_every_agent_identically(self) -> None:
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        agents = payload["agents"]
        known_names = sorted(
            {
                str(agent.get("name") or "").lower()
                for agent in agents
                if len(str(agent.get("name") or "").strip())
                >= MIN_AGENT_NAME_STRIP_CHARS
            },
            key=len,
            reverse=True,
        )
        python_rows = {
            agent["name"]: classify(agent.get("task"), known_names)
            for agent in agents
        }
        completed = subprocess.run(
            ["node", str(JS_TEST), str(FIXTURE), "--json"],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        javascript_rows = {
            row["name"]: {
                "quality": row["quality"],
                "residue": row["residue"],
                "signal_chars": row["signal_chars"],
            }
            for row in json.loads(completed.stdout)
        }
        self.assertEqual(python_rows, javascript_rows)
        self.assertEqual(len(python_rows), 36)


if __name__ == "__main__":
    unittest.main(verbosity=2)
