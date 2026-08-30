"""Comment extraction, one entry point per supported language family."""
import os
from collections.abc import Mapping

from .base import Comment
from .pysrc import UnparseableSource

TSJS_EXT = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts"}
PY_EXT = {".py", ".pyi"}
MD_EXT = {".md", ".markdown"}

# The three extractors a `languageExtensions` config key can extend. "c-style"
# runs the TS/JS state machine, which is a reasonable stand-in for // and
# /* */ comments generally -- it just also understands template literals and
# regex literals that only JS has, and those never fire on code that has
# neither.
FAMILIES: dict[str, frozenset[str]] = {
    "c-style": frozenset(TSJS_EXT),
    "python-style": frozenset(PY_EXT),
    "markdown": frozenset(MD_EXT),
}
# Walked by default; markdown stays opt-in (see cli.py's --markdown).
DEFAULT_WALK_FAMILIES = ("c-style", "python-style")
EXTENSIONS = TSJS_EXT | PY_EXT

ExtraExtensions = Mapping[str, "list[str] | frozenset[str]"]

__all__ = [
    "Comment", "UnparseableSource", "EXTENSIONS", "MD_EXT", "FAMILIES",
    "DEFAULT_WALK_FAMILIES", "language_of", "extract", "extract_file",
]


def language_of(path: str, extra: ExtraExtensions | None = None) -> str | None:
    """The language family `path` belongs to, defaults plus `extra`'s additions.

    `extra` is a config's already-validated `languageExtensions`: family name
    to the extra extensions it claims, on top of `FAMILIES`' own.
    """
    ext = os.path.splitext(path)[1].lower()
    for family, exts in FAMILIES.items():
        if ext in exts:
            return family
    if extra:
        for family, extra_exts in extra.items():
            if ext in extra_exts:
                return family
    return None


def extract(path: str, src: str, extra: ExtraExtensions | None = None) -> list[Comment]:
    """Every comment in `src`. Raises UnparseableSource for broken Python."""
    lang = language_of(path, extra)
    if lang == "c-style":
        from . import tsjs

        return tsjs.extract(path, src)
    if lang == "python-style":
        from . import pysrc

        return pysrc.extract(path, src)
    if lang == "markdown":
        from . import markdown

        return markdown.extract(path, src)
    return []


def extract_file(path: str, extra: ExtraExtensions | None = None) -> list[Comment]:
    with open(path, encoding="utf-8-sig", errors="replace", newline="") as f:
        return extract(path, f.read(), extra)
