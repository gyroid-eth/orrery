"""Cockpit UI text is English: no Japanese in user-visible strings.

Covers the strings the operator sees after SEND, the History "find in
terminal" results and the composer's slash-command descriptions. Code
comments may stay Japanese, so comment lines are skipped.
"""
import pathlib
import re
import sys

BRIDGE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRIDGE))

JAPANESE = re.compile(r"[぀-ヿ㐀-鿿！-｠]")


def _code_lines(path):
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), path.read_text(encoding="utf-8"), flags=re.S)
    for number, line in enumerate(text.splitlines(), 1):
        code = re.sub(r"(^|\s)//\s.*$", "", line)
        if code.strip().startswith("//"):
            continue
        yield number, code


def test_conversation_view_strings_have_no_japanese():
    hits = [f"{n}: {c.strip()[:120]}" for n, c in _code_lines(BRIDGE / "conversation_view.js") if JAPANESE.search(c)]
    assert hits == []


def test_builtin_slash_descriptions_are_english():
    import orrery_backend

    hits = [
        (program, entry["name"], entry["description"])
        for program, entries in orrery_backend._BUILTIN_SLASH.items()
        for entry in entries
        if JAPANESE.search(entry["description"])
    ]
    assert hits == []
