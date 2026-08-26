"""Find comments in TS/JS source with a character state machine.

A regex-based extractor cannot do this: `//` inside a string literal, `/*`
inside a regex character class, and a URL in a quoted path all look exactly
like comment openers to a pattern matcher. Tracking the lexical state is the
only way to tell them apart, and the state machine is small enough to read.

The hard case is `/`, which starts a regex literal in some positions and is
division in others. JavaScript resolves this from the previous significant
token, and so do we.

Nesting is a stack of frames rather than recursion, because `${}` inside a
template inside a `${}` is legal and unbounded. Comments are only recognised in
a code frame, which is what keeps `// not a comment` inside a template quiet.

Errors are bounded to one line on purpose. A string or regex literal cannot
contain a raw newline, so hitting one means the scan is already wrong; treating
that as the end of the literal confines the damage to the line that caused it
instead of letting a stray quote swallow the rest of the file.
"""
from bisect import bisect_right
from typing import cast

from .base import Comment
from .normalize import normalize

IDENT = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_$")

# after these a `/` opens a regex; after a value (identifier, `)`, `]`) it divides
REGEX_OK_CHARS = set("(,=:[!&|?{};+-*%<>~^")
REGEX_OK_WORDS = {
    "return", "typeof", "instanceof", "in", "of", "new", "delete", "void",
    "case", "do", "else", "yield", "await", "throw",
}

# (start offset, end offset, kind) for one scanned comment
Span = tuple[int, int, str]


def extract(path: str, src: str) -> list[Comment]:
    """Return every comment in `src`, in source order."""
    spans = scan(src)
    if not spans:
        return []
    starts = _line_starts(src)
    return _merge_runs([_to_comment(path, src, starts, s) for s in spans])


def _merge_runs(comments: list[Comment]) -> list[Comment]:
    """Fold a run of `//` lines into the one comment its author wrote.

    Left split, each line is scored as its own comment, and the model was
    trained on whole ones -- so a continuation like "and this is where the
    author is reading it." arrives as a sentence fragment and gets a confident
    verdict on prose nobody wrote.
    """
    out: list[Comment] = []
    for c in comments:
        prev = out[-1] if out else None
        # against the run's last line, not its first: a merged comment keeps
        # the starting line number, so a third line would look two lines away
        if (
            prev is not None
            and c.kind == prev.kind == "line"
            and c.line == prev.line + prev.raw.count("\n") + 1
            and c.col == prev.col
        ):
            raw = prev.raw + "\n" + c.raw
            out[-1] = Comment(
                prev.path, prev.line, prev.col, "line", raw, normalize(raw, "line"),
                c.end_line, c.end_col,
            )
            continue
        out.append(c)
    return out


def scan(src: str) -> list[Span]:
    """Return [(start, end, kind)] for every comment, positions as offsets."""
    out: list[Span] = []
    n = len(src)
    i = 0
    prev: str | None = None  # last significant token: a punctuation char, or "v" for a value
    stack: list[int | str] = []  # template/code frames above the outermost code frame
    depth = 0  # brace depth within the current code frame

    while i < n:
        c = src[i]

        if stack and stack[-1] == "template":
            if c == "\\":
                i += 2
            elif c == "`":
                stack.pop()
                prev, i = "v", i + 1
            elif c == "$" and i + 1 < n and src[i + 1] == "{":
                stack.append(depth)
                stack.append("code")
                depth, i = 0, i + 2
            else:
                i += 1
            continue

        if c == "/" and i + 1 < n and src[i + 1] == "/":
            start = i
            while i < n and src[i] != "\n":
                i += 1
            out.append((start, i, "line"))
            continue

        if c == "/" and i + 1 < n and src[i + 1] == "*":
            start = i
            i += 2
            while i < n and not (src[i] == "*" and i + 1 < n and src[i + 1] == "/"):
                i += 1
            i = min(i + 2, n)  # an unterminated block really does run to EOF
            doc = src.startswith("/**", start) and not src.startswith("/**/", start)
            out.append((start, i, "doc" if doc else "block"))
            prev = None
            continue

        if c in "'\"":
            i = _skip_quoted(src, i, c)
            prev = "v"
            continue

        if c == "`":
            stack.append("template")
            i += 1
            continue

        if c == "/" and _regex_allowed(prev):
            j = _skip_regex(src, i)
            if j is not None:
                prev, i = "v", j
                continue

        if c in IDENT:
            start = i
            while i < n and src[i] in IDENT:
                i += 1
            word = src[start:i]
            prev = word if word in REGEX_OK_WORDS else "v"
            continue

        if c == "{":
            depth += 1
        elif c == "}":
            if depth == 0 and stack and stack[-1] == "code":
                stack.pop()
                # the frame below "code" is always the int depth pushed alongside
                # it (see the push above); the mixed-type stack just can't say so
                depth = cast(int, stack.pop())
                prev, i = "v", i + 1
                continue
            depth = max(0, depth - 1)

        if not c.isspace():
            prev = c
        i += 1

    return out


def _regex_allowed(prev: str | None) -> bool:
    if prev is None:
        return True
    if prev == "v":
        return False
    if len(prev) > 1:
        return prev in REGEX_OK_WORDS
    return prev in REGEX_OK_CHARS


def _skip_quoted(src: str, i: int, quote: str) -> int:
    """Index just past the closing quote, or at the newline that proves an error."""
    n = len(src)
    i += 1
    while i < n:
        c = src[i]
        if c == "\\":
            i += 2
            continue
        if c == "\n":
            return i
        if c == quote:
            return i + 1
        i += 1
    return n


def _skip_regex(src: str, i: int) -> int | None:
    """Index just past the closing `/` and flags, or None if this was division.

    A regex literal cannot span a line, so a newline means the `/` was division
    after all and the caller re-reads it as ordinary code.
    """
    n = len(src)
    j = i + 1
    in_class = False
    while j < n:
        c = src[j]
        if c == "\\":
            j += 2
            continue
        if c == "\n":
            return None
        if c == "[":
            in_class = True
        elif c == "]":
            in_class = False
        elif c == "/" and not in_class:
            j += 1
            while j < n and src[j] in IDENT:
                j += 1
            return j
        j += 1
    return None


def _line_starts(src: str) -> list[int]:
    starts = [0]
    for i, c in enumerate(src):
        if c == "\n":
            starts.append(i + 1)
    return starts


def _to_comment(path: str, src: str, starts: list[int], span: Span) -> Comment:
    start, end, kind = span
    li = bisect_right(starts, start) - 1
    col = start - starts[li] + 1
    end_li = bisect_right(starts, end - 1) - 1 if end > start else li
    end_col = end - starts[end_li] + 1
    if kind == "line" and src[starts[li] : start].strip():
        kind = "trailing"
    raw = src[start:end]
    return Comment(
        path, li + 1, col, kind, raw, normalize(raw, "line" if kind in ("line", "trailing") else "block"),
        end_li + 1, end_col,
    )
