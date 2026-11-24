"""Demo mode masks the user and machine name on screen only (2026-09-30).

Run from bridge/: ``python -m pytest tests/test_demo_mask.py``.

demo_mask.js is plain JavaScript; these tests run it in node. The names are
made up ("mira", "ミラ", "mira-studio"): nothing here reads the real account.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
BRIDGE = HERE.parent
MASK_JS = BRIDGE / "demo_mask.js"
NODE = shutil.which("node")
IDENTITY = {"users": ["mira", "ミラ", "anne"], "hosts": ["mira-studio.local", "mira-studio"]}

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")


def run(script: str, **data) -> object:
    """Run `script` in node with M (the module), m (a masker for IDENTITY)
    and D (the data) defined; it prints JSON."""
    prelude = (f"const M=require({json.dumps(str(MASK_JS))});"
               f"const m=M.create({json.dumps(IDENTITY)});"
               f"const D={json.dumps(data)};")
    done = subprocess.run([NODE, "-e", prelude + script], capture_output=True, text=True, check=True)
    return json.loads(done.stdout)


def mask(*texts: str) -> list[str]:
    return run("console.log(JSON.stringify(D.t.map(t=>m.mask(t))))", t=list(texts))


# ---------------------------------------------------------------- positive

@pytest.mark.parametrize("text, shown", [
    ("/Users/mira/work/notes.md", "/Users/****/work/notes.md"),
    ("cd /home/mira", "cd /home/****"),
    ("C:\\Users\\mira\\Desktop", "C:\\Users\\****\\Desktop"),
    ("/mnt/c/Users/mira/Downloads", "/mnt/c/Users/****/Downloads"),
    ("file:///Users/mira/a.png", "file:///Users/****/a.png"),
    ("see /USERS/Mira/x", "see /USERS/****/x"),                      # any letter case
    ("mira@mira-studio ~ %", "****@*********** ~ %"),                # a shell prompt
    ("ssh mira-studio.local", "ssh *****************"),
    ("/Users/ミラ/メモ", "/Users/＊＊/メモ"),                           # wide characters, wide masks
])
def test_positive_names_are_masked_in_place(text, shown):
    assert mask(text) == [shown]
    assert len(shown) == len(text)


def test_positive_the_mask_keeps_the_display_width():
    widths = run("""
      const w=s=>[...s].reduce((n,c)=>n+(/[\\u3000-\\u9fff\\uff00-\\uff60]/.test(c)?2:1),0);
      console.log(JSON.stringify(D.t.map(t=>[w(t),w(m.mask(t))])));""",
                 t=["/Users/ミラ/x", "/Users/mira/x", "mira@mira-studio $"])
    assert all(before == after for before, after in widths)


def test_positive_a_colour_change_inside_a_name_does_not_hide_it_from_the_mask():
    """Review P2-4."""
    assert mask("/Users/mi\x1b[31mra\x1b[0m/private.txt") == ["/Users/**\x1b[31m**\x1b[0m/private.txt"]


@pytest.mark.parametrize(("raw", "shown"), [
    ("/mnt/c/Users/Profile/work", "/mnt/c/Users/*******/work"),
    (r"C:\Users\Profile\work", r"C:\Users\*******\work"),
    ("D:/Users/Other Profile/work", "D:/Users/*************/work"),
    ("/mnt/d/Users/Other Profile", "/mnt/d/Users/*************"),
])
def test_windows_profiles_are_hidden_without_a_windows_login_name(raw, shown):
    result = run("""
      console.log(JSON.stringify([
        m.project(D.raw,{wholePath:true}).text,
        m.project('Working directory: '+D.raw,{literalPath:D.raw}).text,
        m.terminal(D.raw+'/work')
      ]));
    """, raw=raw)
    assert result == [shown, f"Working directory: {shown}", shown + "/work"]


def test_positive_a_screen_repainted_row_by_row_keeps_its_rows_apart():
    """Found on the real terminal: tmux repaints with a cursor move before each
    row and no line break, so "…page" + "mira@…" and "/Users/mira" + "mira@…"
    ran together into one word and were not masked."""
    rows = ("\x1b[1;1Hlast page\x1b[K\x1b[2;1Hmira@mira-studio:~$ pwd"
            "\x1b[3;1H/Users/mira\x1b[4;1Hmira@mira-studio:~$ ")
    assert mask(rows) == [rows.replace("mira@mira-studio", "****@***********").replace("/Users/mira", "/Users/****")]


# ---------------------------------------------------------------- negative

@pytest.mark.parametrize("text", [
    "ask mira later",            # the name as an ordinary word
    "admiral",                   # inside another word
    "/Users/miranda/x",          # a different user whose name starts the same
    "/Users/shared/mira",        # the name deeper in a path, not the home folder
    "amira@example.com",         # a longer name before @
    "mira-studios",              # a longer host name
    "~/work/notes.md",           # already short
])
def test_negative_other_text_is_left_alone(text):
    assert mask(text) == [text]


def test_negative_without_names_nothing_changes():
    result = run("""
      const off=M.create({});
      console.log(JSON.stringify([off.active,off.mask(D.t)]));""",
                 t="/Users/mira/x mira@mira-studio")
    assert result == [False, "/Users/mira/x mira@mira-studio"]


# ---------------------------------------------------------------- backend

def test_identity_comes_from_home_and_the_host_name(monkeypatch):
    sys.path.insert(0, str(BRIDGE))
    import orrery_backend as ob
    import socket
    monkeypatch.setenv("HOME", "/Users/mira")
    monkeypatch.setattr(socket, "gethostname", lambda: "mira-studio.local")
    monkeypatch.setattr(ob, "windows_user", lambda: "")
    identity = ob.demo_identity()
    assert identity["home"] == "/Users/mira"
    assert identity["users"][0] == "mira"
    assert identity["hosts"] == ["mira-studio.local", "mira-studio"]


def test_the_page_loads_the_masker_before_it_connects():
    html = (BRIDGE / "cockpit.html").read_text(encoding="utf-8")
    assert html.index('<script src="demo_mask.js">') < html.index('<script src="demo_mode.js">')
    assert "OrreryDemo.ready.then(connect);" in html
    assert "\nconnect();\n" not in html


# ---------------------------------------------------------------- added words
# Words the user adds (a person's name written in Mail, a project name). Made up.

def words_mask(words, *texts):
    return run("const w=M.create({...D.id,words:D.words});console.log(JSON.stringify(D.t.map(t=>w.mask(t))))",
               id=IDENTITY, words=words, t=list(texts))


@pytest.mark.parametrize("text, shown", [
    ("Ask Kobo now", "Ask **** now"),
    ("KOBO.", "****."),                         # any letter case
    ("kobo@example", "****@example"),
    ("from Anne Lee:", "from ********:"),       # a word with a space
    ("ミラノさんへ", "＊＊＊さんへ"),              # a word in Japanese: anywhere, wide masks
])
def test_positive_added_words_are_masked(text, shown):
    assert words_mask(["Kobo", "Anne Lee", "ミラノ"], text) == [shown]


@pytest.mark.parametrize("text", ["kobold", "x_kobo", "Kobo2", "Annie Lee"])
def test_negative_an_added_latin_word_inside_another_word_is_left_alone(text):
    assert words_mask(["Kobo", "Anne Lee"], text) == [text]


def test_negative_one_letter_words_and_blank_entries_are_ignored():
    assert words_mask(["a", " ", ""], "a cat") == ["a cat"]


@pytest.mark.parametrize(("raw", "shown"), [
    ("Go to https://demo.invalid:8443/private?a=secret&b=long#fragment.", "Go to [URL]."),
    ("(wss://demo.invalid/folder[a](b)) and www.demo.invalid/private", "([URL]) and [URL]"),
    ("mailto:someone@desk.invalid", "[URL]"),
    ("file:///var/link%20target/report.png", "[path]"),
    ("file://private-host/shares/report.png", "[path]"),
    ("file:///C:/Users/mira/a.png", "[path]"),
    ("Read /var/lab/private.png then continue", "Read [path] then continue"),
    ("~/secret/日本語.txt", "[path]"),
    (r"Try C:\Program Files\Private\report name.png now", "Try [path] now"),
    (r"Copy \\private-host\shared\report.txt", "Copy [path]"),
    (r"Open /tmp/Red\ Room/private.png and /tmp/other", "Open [path] and [path]"),
    ('Use "/tmp/Red Room/no extension" and continue', 'Use "[path]" and continue'),
    ("<script>alert(1)</script> <img src=\"/tmp/private.png\" onerror=\"alert(2)\">",
     '<script>alert(1)</script> <img src="[path]" onerror="alert(2)">'),
])
def test_strict_location_mask_uses_fixed_labels(raw, shown):
    assert run("""
      const strict=M.create({...D.id,hideLocations:true});
      console.log(JSON.stringify(strict.mask(D.raw)));
    """, id=IDENTITY, raw=raw) == shown


def test_strict_clipboard_offsets_and_known_labels():
    result = run("""
      const strict=M.create({...D.id,hideLocations:true});
      const result=strict.project(D.raw);
      const src=(start,end)=>D.raw.slice(M.originalOffset(start,result.ranges),
        M.originalOffset(end,result.ranges,true));
      console.log(JSON.stringify([
        result.text,src(3,5),src(9,14),src(0,result.text.length),
        strict.project('Preview notes without suffix',{literalPath:'notes without suffix'}).text,
        strict.project('Only a file name',{wholePath:true}).text
      ]));
    """, id=IDENTITY, raw="a https://secret.invalid/a + /very/long/filename b")
    assert result == ["a [URL] + [path] b", "https://secret.invalid/a",
                      " /very/long/filename", "a https://secret.invalid/a + /very/long/filename b",
                      "Preview [path]", "[path]"]


def test_terminal_renders_fixed_markers_in_original_columns():
    url = "https://secret.invalid/abc"
    raw = f"Go {url} then \x1b[31m~/private/日本語.txt\x1b[0m!"
    result = run("""
      let strict=M.create({...D.id,hideLocations:true});
      let out=strict.terminal(D.raw);
      console.log(JSON.stringify([out, D.raw.length===out.length]));
    """, id=IDENTITY, raw=raw)
    assert result == ["Go <>" + " " * (len(url) - 2) + " then \x1b[31m[]        \u3000\u3000\u3000    \x1b[0m!", True]
