"""Find prose-bearing blocks in markdown using markdown-it-py.

`MarkdownIt("commonmark").parse(src)` produces a flat token stream. Every
prose-bearing block -- a paragraph, a heading, a list item, a blockquote line
-- emits exactly one token of type `"inline"`, carrying `.content` (the
block's text, with block markers such as `#`, `- ` and `> ` already gone) and
`.map` (its 0-based line span). Fenced code, indented code and raw HTML blocks
never emit an `"inline"` token, so collecting every `"inline"` token from the
flat stream already excludes them.

A leading YAML front-matter block is blanked out before parsing rather than
left in place, because markdown-it does not recognize it as front matter: the
closing `---` parses as a setext heading underline for the line above it, not
as a delimiter. Blanking (not deleting) the lines keeps every later line
number unchanged.

An HTML comment is the only span every CommonMark context leaves untouched --
it stays literal inside a fenced block, a table cell or a blockquote, where a
`#`-style directive would either be swallowed as prose or need its own escaping
rules. `<!-- commentlint-off -->` and `<!-- commentlint-on -->` on their own
lines toggle a disabled range; a block whose line span touches any disabled
line is dropped before scoring. An unterminated `commentlint-off` disables the
rest of the file.
"""
import re

from .base import Comment

FRONT_MATTER_CLOSERS = ("---", "...")
OFF_RE = re.compile(r"<!--\s*commentlint-off\s*-->")
ON_RE = re.compile(r"<!--\s*commentlint-on\s*-->")


def _strip_front_matter(src: str) -> str:
    lines = src.split("\n")
    if not lines or lines[0].rstrip("\r") != "---":
        return src
    for i in range(1, len(lines)):
        if lines[i].rstrip("\r") in FRONT_MATTER_CLOSERS:
            for j in range(i + 1):
                lines[j] = ""
            return "\n".join(lines)
    return src


def _disabled_lines(lines: list[str]) -> list[bool]:
    """True for every line inside a commentlint-off / commentlint-on block, both markers included."""
    disabled = []
    off = False
    for line in lines:
        if OFF_RE.search(line):
            off = True
        disabled.append(off)
        if ON_RE.search(line):
            off = False
    return disabled


def extract(path: str, src: str) -> list[Comment]:
    """Every prose-bearing block in `src`, one Comment per markdown-it inline token."""
    from markdown_it import MarkdownIt

    stripped = _strip_front_matter(src)
    lines = stripped.split("\n")
    disabled = _disabled_lines(lines)
    tokens = MarkdownIt("commonmark").parse(stripped)

    out: list[Comment] = []
    for tok in tokens:
        if tok.type != "inline" or tok.map is None:
            continue
        text = " ".join(tok.content.split())
        if not text:
            continue
        start, end = tok.map
        if any(disabled[start:end]):
            continue
        raw = "\n".join(lines[start:end])
        end_col = len(lines[end - 1]) + 1
        out.append(Comment(path, start + 1, 1, "prose", raw, text, end, end_col))
    return out
