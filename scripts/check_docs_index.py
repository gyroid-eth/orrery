#!/usr/bin/env python3
"""Check that both documentation indexes cover every Markdown article."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit


def check(root: Path) -> list[str]:
    root = root.resolve()
    docs = root / "docs"
    indexes = [docs / "README.md", docs / "en/README.md"] if (docs / "en").is_dir() else [docs / "README.md", docs / "README.en.md"]
    articles = {p.resolve() for p in docs.rglob("*.md")} - {p.resolve() for p in indexes}
    linked: set[Path] = set()
    errors: list[str] = []
    for index in indexes:
        if not index.is_file():
            errors.append(f"missing index: {index.relative_to(root)}")
            continue
        # These indexes use inline Markdown links, one article per list item.
        for raw in re.findall(r"\[[^\]]*\]\(([^)]+)\)", index.read_text(encoding="utf-8")):
            url = urlsplit(raw.strip("<>"))
            if url.scheme or url.netloc or not url.path:
                continue
            target = (index.parent / unquote(url.path)).resolve()
            if not target.is_file():
                errors.append(f"broken link in {index.relative_to(root)}: {raw}")
            elif target.suffix == ".md":
                linked.add(target)
    for path in sorted(articles - linked):
        errors.append(f"unindexed article: {path.relative_to(root)}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1], help="repository root (default: this checkout)")
    root = parser.parse_args().root.resolve()
    errors = check(root)
    if errors:
        for error in errors:
            print(error)
        return 1
    docs = root / "docs"
    articles = sum(1 for p in docs.rglob("*.md")) - 2
    assets = sum(1 for p in docs.rglob("*") if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"})
    print(f"OK: {articles} Markdown articles indexed; {assets} accompanying image/GIF assets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
