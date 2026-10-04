"""Exercise the documentation gate used by the CLI and tools CI suite."""
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check_docs_index.py"


def run_check(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECKER), "--root", str(root)],
        capture_output=True, text=True, check=False,
    )


def make_docs(root: Path, language: str = "both", *, indexed: bool = True) -> None:
    docs = root / "docs"
    (docs / "en").mkdir(parents=True)
    if language in {"both", "ja"}:
        (docs / "topic.md").write_text("# 日本語の説明\n", encoding="utf-8")
    if language in {"both", "en"}:
        (docs / "en" / "topic.md").write_text("# English instructions\n", encoding="utf-8")
    # The single-language fixtures are completely indexed: the old coverage
    # gate accepts them. Only the new counterpart check should reject them.
    ja_target = "en/topic.md" if language == "en" else "topic.md"
    en_target = "../topic.md" if language == "ja" else "topic.md"
    ja_link = f"[説明]({ja_target})\n" if indexed else ""
    en_link = f"[Instructions]({en_target})\n" if indexed else ""
    (docs / "README.md").write_text("# 索引\n\n" + ja_link, encoding="utf-8")
    (docs / "en" / "README.md").write_text("# Index\n\n" + en_link, encoding="utf-8")


def test_repository_docs_are_indexed_and_paired() -> None:
    result = run_check(ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Japanese/English file pairs" in result.stdout


def test_complete_indexed_pair_is_accepted(tmp_path: Path) -> None:
    make_docs(tmp_path)
    result = run_check(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 Markdown articles indexed" in result.stdout
    assert "2 Japanese/English file pairs" in result.stdout


@pytest.mark.parametrize(
    ("language", "error"),
    [
        ("ja", "missing English counterpart: docs/en/topic.md (Japanese: docs/topic.md)"),
        ("en", "missing Japanese counterpart: docs/topic.md (English: docs/en/topic.md)"),
    ],
)
def test_single_language_is_rejected_even_when_indexed(
    tmp_path: Path, language: str, error: str,
) -> None:
    make_docs(tmp_path, language)
    result = run_check(tmp_path)
    assert result.returncode == 1
    assert result.stdout.splitlines() == [error]
    assert not result.stderr


def test_pair_does_not_bypass_index_coverage(tmp_path: Path) -> None:
    make_docs(tmp_path, indexed=False)
    result = run_check(tmp_path)
    assert result.returncode == 1
    assert set(result.stdout.splitlines()) == {
        "unindexed article: docs/topic.md",
        "unindexed article: docs/en/topic.md",
    }
