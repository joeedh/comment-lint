"""Split prose into sentences for --split-sentences / splitSentences mode.

A regex splitter, not a full sentence tokenizer -- sentence boundaries are
inherently heuristic, and pulling in nltk/spacy just for this would cost more
import time than the whole scoring backend budgets for scikit-learn. Periods
that belong to a known abbreviation or a single-letter initial are protected
before splitting so "e.g. this" and "J. Smith" don't end a sentence early.
"""
import re

_ABBREV = re.compile(
    r"\b(?:[A-Za-z]|e\.g|i\.e|etc|vs|mr|mrs|ms|dr|prof|sr|jr|st|vol|fig|no|approx|cf|al)\.",
    re.I,
)
_PLACEHOLDER = "\0"
_BOUNDARY = re.compile(r"(?<=[.!?])[\"')\]]?\s+(?=[A-Z0-9\"'(])")


def protect(text: str) -> str:
    """Returns `text` with each abbreviation's period swapped for a same-length placeholder.

    The result lines up with `text` character for character, so a caller that needs
    offsets can split the protected copy and index the original.
    """
    return _ABBREV.sub(lambda m: m.group(0).replace(".", _PLACEHOLDER), text)


def split(text: str) -> list[str]:
    """Sentences in `text`, in reading order, each collapsed to single-spaced prose."""
    text = " ".join(text.split())
    if not text:
        return []
    protected = protect(text)
    parts = _BOUNDARY.split(protected)
    return [p.replace(_PLACEHOLDER, ".").strip() for p in parts if p.strip()]
