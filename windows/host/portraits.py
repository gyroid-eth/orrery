"""Portraits and the names that go with them.

The repository's public-domain portraits (assets/portraits_64, see
CREDITS.md) are scientists, one file per surname. An agent named after one
of them wears that portrait, as in the original cockpit (portrait_stem in
bridge/orrery_backend.py); any other name gets a stable pick by hash. An
agent created without a name is given a scientist's name nobody uses yet.
"""
from __future__ import annotations

import random
from pathlib import Path

PORTRAITS = Path(__file__).resolve().parents[2] / "assets" / "portraits_64"


def stems(base: Path = PORTRAITS) -> list[str]:
    return sorted(p.stem for p in base.glob("*.png"))


def hash_index(name: str, count: int) -> int:
    value = 0
    for ch in name.lower():
        value = (value * 31 + ord(ch)) & 0xFFFFFFFF
    return value % count


def portrait_stem(name: str, base: Path = PORTRAITS) -> str | None:
    """The portrait an agent wears: its namesake's if there is one, else one by hash."""
    names = stems(base)
    if not names or not name:
        return None
    lowered = name.lower()
    for stem in names:
        if stem.lower() == lowered:
            return stem
    return names[hash_index(name, len(names))]


def random_name(taken, base: Path = PORTRAITS, rng: random.Random | None = None) -> str:
    """A scientist's name not in ``taken`` (compared without case).

    Once every name is in use, the same names come round again with a
    number: Curie2, Curie3, ...
    """
    rng = rng or random.Random()
    used = {str(n).lower() for n in taken}
    names = stems(base) or ["Agent"]
    free = [n for n in names if n.lower() not in used]
    if free:
        return rng.choice(free)
    for number in range(2, 10_000):
        free = [f"{n}{number}" for n in names if f"{n}{number}".lower() not in used]
        if free:
            return rng.choice(free)
    raise RuntimeError("no free name")
