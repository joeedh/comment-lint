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
"""
from .base import Comment

FRONT_MATTER_CLOSERS = ("---", "...")


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


def extract(path: str, src: str) -> list[Comment]:
    """Every prose-bearing block in `src`, one Comment per markdown-it inline token."""
    from markdown_it import MarkdownIt

    stripped = _strip_front_matter(src)
    lines = stripped.split("\n")
    tokens = MarkdownIt("commonmark").parse(stripped)

    out: list[Comment] = []
    for tok in tokens:
        if tok.type != "inline" or tok.map is None:
            continue
        text = " ".join(tok.content.split())
        if not text:
            continue
        start, end = tok.map
        raw = "\n".join(lines[start:end])
        end_col = len(lines[end - 1]) + 1
        out.append(Comment(path, start + 1, 1, "prose", raw, text, end, end_col))
    return out
