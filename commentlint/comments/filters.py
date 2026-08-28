"""Decide which comments are prose worth scoring.

The model was trained on hand-written prose about code. Directives, license
headers and commented-out code are none of those, and feeding them in produces
confident nonsense: a real Apache header scores 0.64, over the calibrated 0.50
cut, purely because legal boilerplate does not read like a good code comment.

Commented-out code is a genuine finding (rule C2) but not a prose one, so it is
reported directly from the heuristic and never sent to the model, and it is
tagged in `--json` so the provenance stays visible.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .. import unicode_whitelist

if TYPE_CHECKING:
    from .base import Comment

MIN_LEN = 40  # excludes 2.9% of the training corpus and most `// TODO` noise
LATIN1_MAX = 0xFF  # rule C13's ceiling: prose stays in Latin-1 unless whitelisted

DIRECTIVE = re.compile(
    r"^\s*(?:"
    r"eslint-|tslint:|prettier-ignore|@ts-|c8 |v8 |istanbul |jshint |globals?\s|"
    r"type:\s*ignore|noqa|pragma:|pylint:|mypy:|fmt:\s*(?:on|off)|isort:|"
    r"!|-\*-|coding[:=]|#!"
    r")",
    re.I,
)

LICENSE = re.compile(
    r"copyright|licen[cs]e|SPDX|Permission is hereby granted|"
    r"All rights reserved|Licensed under|WITHOUT WARRANTIES",
    re.I,
)

_CODE_SIGNS = (
    re.compile(r"[;{}]\s*$"),
    re.compile(r"^\s*(?:const|let|var|function|class|import|export|return|if|for|while|def|elif)\b.*[:;{(]"),
    re.compile(r"\w+\s*\([^)]*\)\s*[;{]"),
    re.compile(r"=>\s*[{(]"),
    re.compile(r"^\s*[\w.\[\]]+\s*[-+*/|&]?=[^=]"),
    re.compile(r"^\s*</?\w+[^>]*>"),
    re.compile(r"^\s*[}\])]"),
)


def is_directive(text: str, raw: str) -> bool:
    return bool(DIRECTIVE.match(raw.lstrip("/*# ")) or DIRECTIVE.match(text))


def is_license(text: str) -> bool:
    return bool(LICENSE.search(text[:400]))


def looks_like_code(text: str) -> bool:
    """True when the comment is commented-out code rather than prose.

    Deliberately biased toward prose: every line has to look like code before
    the whole comment does, so a sentence that merely quotes an expression is
    left alone.
    """
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if not lines:
        return False
    hits = sum(1 for ln in lines if any(p.search(ln) for p in _CODE_SIGNS))
    if hits < len(lines):
        return False
    return _low_prose(text)


def _low_prose(text: str) -> bool:
    """Code is punctuation-dense and short on ordinary words."""
    words = re.findall(r"[A-Za-z]{2,}", text)
    if len(words) < 3:
        return True
    punct = sum(1 for c in text if c in "{}[]();=<>|&")
    return punct / max(1, len(text)) > 0.04


def disallowed_codepoints(text: str, whitelist: unicode_whitelist.Ranges) -> list[int]:
    """Distinct codepoints above Latin-1 in `text`, first-seen order, minus `whitelist`."""
    found: list[int] = []
    seen: set[int] = set()
    for ch in text:
        cp = ord(ch)
        if cp > LATIN1_MAX and cp not in seen and not unicode_whitelist.contains(whitelist, cp):
            seen.add(cp)
            found.append(cp)
    return found


def classify(comment: "Comment") -> str:
    """Return `prose`, `skip`, or `code` for one extracted comment."""
    text = comment.text
    if len(text) < MIN_LEN:
        return "skip"
    if is_directive(text, comment.raw):
        return "skip"
    if is_license(text):
        return "skip"
    if looks_like_code(text):
        return "code"
    return "prose"


def classify_markdown(text: str) -> str:
    """Return `prose` or `skip` for one extracted markdown block.

    None of `classify`'s heuristics describe markdown -- there is no comment
    delimiter to mistake for a directive, and a fenced block is already
    excluded at extraction, so length is the only filter.
    """
    return "skip" if len(text) < MIN_LEN else "prose"
