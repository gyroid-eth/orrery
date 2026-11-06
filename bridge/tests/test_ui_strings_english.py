"""Cockpit UI text is English: no Japanese in user-visible strings.

Covers the strings the operator sees after SEND, the History "find in
terminal" results and the composer's slash-command descriptions. Code
comments may stay Japanese, so a small scanner blanks comments but
keeps string literals ("//" inside a string is still checked).
"""
import pathlib
import re
import sys

BRIDGE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRIDGE))

JAPANESE = re.compile(r"[぀-ヿ㐀-鿿！-｠]")


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


def _japanese_lines(source):
    return [
        f"{n}: {line.strip()[:120]}"
        for n, line in enumerate(_strip_js_comments(source).splitlines(), 1)
        if JAPANESE.search(line)
    ]


def test_scanner_keeps_comment_markers_inside_strings():
    assert _japanese_lines("x='See // 日本語';") == ["1: x='See // 日本語';"]
    assert _japanese_lines('x="/* 日本語 */";') == ['1: x="/* 日本語 */";']
    assert _japanese_lines("x=`a ${f('// 日本語')} b`;") != []
    assert _japanese_lines("x=/['\"]/g;y='日本語';") != []


def test_scanner_drops_real_comments():
    assert _japanese_lines("x=1; // 日本語の注\n/* 日本語\n の注 */ y=2;") == []
    assert _japanese_lines("a=b/c; // 日本語") == []
    assert _strip_js_comments("a\n/* x\ny */b").splitlines()[2].strip() == "b"


def test_conversation_view_strings_have_no_japanese():
    assert _japanese_lines((BRIDGE / "conversation_view.js").read_text(encoding="utf-8")) == []


def test_builtin_slash_descriptions_are_english():
    import orrery_backend

    hits = [
        (program, entry["name"], entry["description"])
        for program, entries in orrery_backend._BUILTIN_SLASH.items()
        for entry in entries
        if JAPANESE.search(entry["description"])
    ]
    assert hits == []
