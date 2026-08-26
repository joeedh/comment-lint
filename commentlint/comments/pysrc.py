"""Find comments and docstrings in Python source using the stdlib.

`tokenize` and `ast` already know what a raw f-string with a nested quote or an
implicitly concatenated triple-quoted literal is. A hand-rolled scanner would
get those wrong, and a wrong extraction is worse than a skipped file, so a
source that will not tokenize is reported rather than guessed at.

Runs of `#` lines are merged into one comment. They are one comment to the
person who wrote them, and the model was trained on multi-line prose.
"""
import ast
import io
import tokenize
from tokenize import TokenInfo

from .base import Comment
from .normalize import normalize

DOC_NODES = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


class UnparseableSource(Exception):
    """The file is not valid Python; the caller should skip and report it."""


def extract(path: str, src: str) -> list[Comment]:
    """Return every comment and docstring in `src`, in source order."""
    out = _hash_comments(path, src) + _docstrings(path, src)
    out.sort(key=lambda c: (c.line, c.col))
    return out


def _hash_comments(path: str, src: str) -> list[Comment]:
    lines = src.splitlines()
    try:
        toks = [
            t for t in tokenize.generate_tokens(io.StringIO(src).readline)
            if t.type == tokenize.COMMENT
        ]
    except (tokenize.TokenError, SyntaxError, IndentationError) as e:
        raise UnparseableSource(str(e)) from e

    out: list[Comment] = []
    run: list[TokenInfo] = []  # consecutive standalone `#` lines, merged on flush

    def flush() -> None:
        if not run:
            return
        first, last = run[0], run[-1]
        raw = "\n".join(t.string for t in run)
        out.append(
            Comment(
                path, first.start[0], first.start[1] + 1, "line", raw, normalize(raw, "python"),
                last.end[0], last.end[1] + 1,
            )
        )
        run.clear()

    for t in toks:
        row, col = t.start
        standalone = not lines[row - 1][:col].strip()
        if not standalone:
            flush()
            out.append(
                Comment(
                    path, row, col + 1, "trailing", t.string, normalize(t.string, "python"),
                    t.end[0], t.end[1] + 1,
                )
            )
            continue
        if run and (row != run[-1].start[0] + 1 or col != run[-1].start[1]):
            flush()
        run.append(t)
    flush()
    return out


def _docstrings(path: str, src: str) -> list[Comment]:
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError) as e:
        raise UnparseableSource(str(e)) from e

    out: list[Comment] = []
    for node in ast.walk(tree):
        if not isinstance(node, DOC_NODES):
            continue
        body = getattr(node, "body", None)
        if not body or not isinstance(body[0], ast.Expr):
            continue
        val = body[0].value
        if not (isinstance(val, ast.Constant) and isinstance(val.value, str)):
            continue
        assert val.end_lineno is not None and val.end_col_offset is not None
        out.append(
            Comment(
                path,
                val.lineno,
                val.col_offset + 1,
                "doc",
                ast.get_source_segment(src, val) or val.value,
                normalize(val.value, "docstring"),
                val.end_lineno,
                val.end_col_offset + 1,
            )
        )
    return out
