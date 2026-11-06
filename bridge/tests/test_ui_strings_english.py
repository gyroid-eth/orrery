"""Cockpit UI text is English: no Japanese in user-visible strings.

Checks every bridge/*.js file, the bridge HTML pages and the composer's
slash-command descriptions. Code comments may stay Japanese, so a small
scanner blanks comments but keeps string literals ("//" inside a string
is still checked). A few strings are Japanese on purpose; ALLOWED names them.
"""
import pathlib
import re
import sys

BRIDGE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRIDGE))

# Kana, kanji, CJK punctuation (、。「」) and full-width forms.
JAPANESE = re.compile(r"[\u3000-\u30ff\u3400-\u9fff\uff01-\uff60]")


# Characters after which a "/" starts a regular expression, not a division.
_REGEX_BEFORE = set("(,=:[!&|?{};+-*%<>~^")
_REGEX_KEYWORDS = ("return", "typeof", "case", "do", "else", "in", "of", "void", "yield", "await")


def _strip_js_comments(source):
    """Blank out JavaScript comments; keep strings, templates and regexes.

    A small scanner, so "//" or "/* */" inside a string literal stays code.
    Newlines are kept, so line numbers still match the file.
    """
    out = []
    i, n = 0, len(source)
    stack = []  # open template literals: brace depth of each ${...}
    depth = 0
    last = ""  # last significant code character or keyword-ending word

    def skip_quoted(j, quote):
        while j < n and source[j] != quote:
            if source[j] == "\\":
                j += 1
            elif source[j] == "\n" and quote != "`":
                raise ValueError("unterminated string")
            j += 1
        return j + 1

    while i < n:
        c = source[i]
        if c == "/" and source.startswith("//", i):
            j = source.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
            continue
        if c == "/" and source.startswith("/*", i):
            j = source.find("*/", i + 2)
            if j < 0:
                raise ValueError("unterminated block comment")
            j += 2
            out.append(re.sub(r"[^\n]", " ", source[i:j]))
            i = j
            continue
        if c in "'\"":
            j = skip_quoted(i + 1, c)
            out.append(source[i:j]); i = j; last = c
            continue
        if c == "`" or (c == "}" and stack and depth == stack[-1]):
            if c == "}":
                stack.pop()
            j = i + 1
            while j < n and source[j] != "`" and not source.startswith("${", j):
                j += 2 if source[j] == "\\" else 1
            if j >= n:
                raise ValueError("unterminated template")
            if source[j] == "`":
                j += 1
            else:
                j += 2
                stack.append(depth)
            out.append(source[i:j]); i = j; last = "`"
            continue
        if c == "/" and (last == "" or last in _REGEX_BEFORE or last in _REGEX_KEYWORDS):
            j, in_class = i + 1, False
            while j < n and (in_class or source[j] != "/"):
                if source[j] == "\\":
                    j += 1
                elif source[j] == "[":
                    in_class = True
                elif source[j] == "]":
                    in_class = False
                elif source[j] == "\n":
                    raise ValueError("unterminated regex")
                j += 1
            j += 1
            while j < n and source[j].isalpha():
                j += 1
            out.append(source[i:j]); i = j; last = "/re"
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        if c.isalnum() or c in "_$":
            m = re.match(r"[\w$]+", source[i:])
            out.append(m.group(0)); i += len(m.group(0)); last = m.group(0)
            continue
        if not c.isspace():
            last = c
        out.append(c)
        i += 1
    if stack:
        raise ValueError("unterminated template")
    return "".join(out)


def _strip_html_comments(source):
    """Blank HTML comments, CSS comments in <style> and JS comments in <script>."""
    blank = lambda text: re.sub(r"[^\n]", " ", text)
    def one(m):
        if m.group("script") is not None:
            return m.group("open") + _strip_js_comments(m.group("script")) + m.group("close")
        if m.group("style") is not None:
            return m.group("sopen") + re.sub(r"/\*.*?\*/", lambda k: blank(k.group(0)), m.group("style"), flags=re.S) + m.group("sclose")
        return blank(m.group(0))
    return re.sub(
        r"(?P<open><script\b[^>]*>)(?P<script>.*?)(?P<close></script>)"
        r"|(?P<sopen><style\b[^>]*>)(?P<style>.*?)(?P<sclose></style>)"
        r"|<!--.*?-->",
        one, source, flags=re.S | re.I,
    )


def _japanese_lines(source, strip=None):
    strip = strip or _strip_js_comments
    return [
        f"{n}: {line.strip()}"
        for n, line in enumerate(strip(source).splitlines(), 1)
        if JAPANESE.search(line)
    ]


# Japanese on purpose (file -> pattern a whole offending line must match).
ALLOWED = {
    # Example of a non-Latin script in the demo-mask help text.
    "cockpit.html": re.compile(r'id="demoMaskWordsHelp".*\(日本語\)'),
    # The full tour asks agents to play shiritori; the words are the game.
    "cockpit_full_tour.js": re.compile(r"\bconst SHIRITORI_PROMPT="),
    # RELAY_JAPANESE: words stripped from Japanese relay text, never shown.
    "roster_descriptor.js": re.compile(r"^\d+: ('[^']*',)+$"),
}


def _bridge_ui_files():
    return sorted([*BRIDGE.glob("*.js"), *BRIDGE.glob("*.html")])


def test_scanner_keeps_comment_markers_inside_strings():
    assert _japanese_lines("x='See // 日本語';") == ["1: x='See // 日本語';"]
    assert _japanese_lines('x="/* 日本語 */";') == ['1: x="/* 日本語 */";']
    assert _japanese_lines("x=`a ${f('// 日本語')} b`;") != []
    assert _japanese_lines("x=/['\"]/g;y='日本語';") != []


def test_scanner_drops_real_comments():
    assert _japanese_lines("x=1; // 日本語の注\n/* 日本語\n の注 */ y=2;") == []
    assert _japanese_lines("a=b/c; // 日本語") == []
    assert _strip_js_comments("a\n/* x\ny */b").splitlines()[2].strip() == "b"


def test_scanner_drops_html_and_css_comments_only():
    page = "<!-- 日本語 -->\n<style>/* 日本語 */ a{}</style>\n<script>// 日本語\nx='日本語';</script>\n<p>日本語</p>"
    assert _japanese_lines(page, _strip_html_comments) == ["4: x='日本語';</script>", "5: <p>日本語</p>"]


def test_japanese_punctuation_counts():
    assert _japanese_lines("x='、';y='「」';") != []


def test_bridge_ui_files_have_no_japanese():
    assert len(_bridge_ui_files()) > 20
    hits = []
    for path in _bridge_ui_files():
        strip = _strip_html_comments if path.suffix == ".html" else _strip_js_comments
        allowed = ALLOWED.get(path.name)
        hits += [
            f"{path.name}:{hit}"
            for hit in _japanese_lines(path.read_text(encoding="utf-8"), strip)
            if not (allowed and allowed.search(hit))
        ]
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
