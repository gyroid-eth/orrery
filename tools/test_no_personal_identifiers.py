#!/usr/bin/env python3
"""Reject developer-machine identifiers in tracked files and commit metadata.

Ported from claude-agent-stack. The first publication candidate of this
repository carried a real telemetry capture as a test fixture: home paths,
the maintainer's username, unpublished research names and collaborators.
A text search for the username was the only thing that noticed, and only
because someone ran it by hand. This test runs it every time.
"""

from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

VAULT_DIRECTORY = b"obsidian" + b"_for_xiaomi"

IDENTIFIERS = (
    b"shuto" + b"ito",
    VAULT_DIRECTORY,
    b"shutos" + b"-macbook",
    b"shut" + b"o",
    b"dr." + b"shuto",
)

ALLOWLIST = {
    # path -> (reason, identifiers that path may contain). Per pattern, not
    # per path: a path-wide excuse would let any future identifier in.
    "tools/test_no_personal_identifiers.py": (
        "The guard names the identifiers it looks for.",
        set(IDENTIFIERS),
    ),
}


def _tracked_paths() -> set[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=True, stdout=subprocess.PIPE
    )
    return {
        os.fsdecode(raw)
        for raw in result.stdout.split(b"\0")
        if raw and ((ROOT / os.fsdecode(raw)).exists() or (ROOT / os.fsdecode(raw)).is_symlink())
    }


def _tracked_bytes(relative_path: str) -> bytes:
    path = ROOT / relative_path
    if path.is_symlink():
        return os.fsencode(os.readlink(path))
    return path.read_bytes()


class NoPersonalIdentifiersTest(unittest.TestCase):
    def test_tracked_files_have_no_unapproved_identifiers(self) -> None:
        tracked = _tracked_paths()
        hits: dict[str, set[bytes]] = {}
        for relative_path in sorted(tracked):
            # Binaries are scanned too; a tracked bundle can hide a whole
            # second history from a text search.
            lowered = _tracked_bytes(relative_path).lower()
            matched = {pattern for pattern in IDENTIFIERS if pattern in lowered}
            if matched:
                hits[relative_path] = matched

        violations = {
            path: sorted(patterns - set(ALLOWLIST.get(path, ("", frozenset()))[1]))
            for path, patterns in hits.items()
            if patterns - set(ALLOWLIST.get(path, ("", frozenset()))[1])
        }
        formatted = [
            f"{path}: {pattern.decode('ascii')}"
            for path, patterns in sorted(violations.items())
            for pattern in patterns
        ]
        self.assertFalse(formatted, "tracked personal identifiers found:\n" + "\n".join(formatted))

        stale = sorted(path for path in ALLOWLIST if path in tracked and path not in hits)
        self.assertFalse(stale, "allowlist entries that no longer contain an identifier: " + ", ".join(stale))

    def test_publishable_history_metadata_has_no_identifiers(self) -> None:
        """Author, committer and message text on the branches that get pushed.

        Only master and release are publication candidates; the local
        backup/dev-history/exp branches keep the pre-rewrite identity and
        must never be pushed. Checking --all would make this test fail on
        every developer clone that still has them.
        """
        refs = ["master"]
        if subprocess.run(["git", "rev-parse", "--verify", "-q", "release"], cwd=ROOT, stdout=subprocess.DEVNULL).returncode == 0:
            refs.append("release")
        fields = subprocess.run(
            ["git", "log", *refs, "--format=%an%n%ae%n%cn%n%ce%n%s%n%b"],
            capture_output=True, check=True, cwd=ROOT,
        ).stdout.lower()
        found = sorted(p.decode("ascii") for p in IDENTIFIERS if p in fields)
        self.assertFalse(found, "identifiers in commit metadata of " + "/".join(refs) + ": " + ", ".join(found))


if __name__ == "__main__":
    unittest.main(verbosity=2)
