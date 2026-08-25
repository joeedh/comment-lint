"""Comment extraction, one entry point per supported language."""
import os

from .base import Comment
from .pysrc import UnparseableSource

TSJS_EXT = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts"}
PY_EXT = {".py", ".pyi"}
EXTENSIONS = TSJS_EXT | PY_EXT

__all__ = ["Comment", "UnparseableSource", "EXTENSIONS", "language_of", "extract", "extract_file"]


def language_of(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in TSJS_EXT:
        return "tsjs"
    if ext in PY_EXT:
        return "python"
    return None


def extract(path, src):
    """Every comment in `src`. Raises UnparseableSource for broken Python."""
    lang = language_of(path)
    if lang == "tsjs":
        from . import tsjs

        return tsjs.extract(path, src)
    if lang == "python":
        from . import pysrc

        return pysrc.extract(path, src)
    return []


def extract_file(path):
    with open(path, encoding="utf-8-sig", errors="replace", newline="") as f:
        return extract(path, f.read())
