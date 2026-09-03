"""Deterministic checkers for rules P13 and P15, the two fenced-interpolation shapes.

P13 says a subordinate alternative is bracketed rather than fenced with paired
commas, because paired commas leave the reader unsure whether the second comma
closes an interpolation or opens a new clause:

    `A file that is not an image, or one carrying the mock marker a real backend
    refuses, fails at upload.`

P15 says the same about paired em dashes. The author's revisions replace or remove a
dash-fenced interpolation five times in six when they touch one, and paired em
dashes are the most recognisable tic of LLM-written prose:

    `Cycles are legal in a VN — looping to a hub scene is normal structure — so
    they are broken for ranking purposes only.`

Both shapes are decidable by structure, unlike P14's, and both report as hard findings.
P13 ships on by default. P15 ships off, because the dash fence is a style call with a
large footprint -- about one comment in thirty of this project's own untouched prose --
so `enableRules: ["P15"]` turns it on. The measurements are in
docs/research/p13-comma-and-dash-interpolation.md and the plan in
docs/plans/p13-p15-interpolation-checkers.md. The examples above sit in backticks so
that this docstring does not flag itself.

This module uses regular expressions only and imports no model backend.
"""
from __future__ import annotations

import re
from typing import Iterator

from .premise import SENTENCE, WORD, Span, masked

COMMA_RULE = "P13"
DASH_RULE = "P15"

# Hashed into the cache run key, so a change to either predicate invalidates
# stored findings without waiting for a release.
CHECK_VERSION = 3

# Only coordinators and alternative markers open a fenced span. Subordinators and
# prepositions ("The handler, if one is registered, runs first") fence ordinary
# adverbial clauses that English punctuates with commas, and on the corpora they
# contributed no true positive.
OPENERS = (
    "or", "and", "nor", "as well as", "rather than", "not", "but not", "plus",
    "including", "such as", "like", "unlike", "especially", "particularly",
)
_OPENER = "|".join(re.escape(o) for o in sorted(OPENERS, key=len, reverse=True))
# The match starts at a sentence start, after clause punctuation, or after an
# opening bracket, so the subject capture cannot begin in the middle of a clause.
COMMA_FENCE = re.compile(
    r"(?:^|[.;:!?]\s+|\(\s*)"
    r"(?P<subject>[^,.;:()—–]{3,80}?),\s+"
    rf"(?P<fenced>(?:{_OPENER})\s[^,.;:()—–`]{{2,90}}),\s+"
    r"(?P<after>[A-Za-z][A-Za-z'’-]*)"
)
# Matches two dashes fencing text inside one sentence. An em dash counts spaced or
# not; an en dash only spaced, since unspaced it is a range or a compound. A dash
# beside a digit is a range ("3 – 5"). The span may wrap across lines but not across
# `;`, `:`, a table pipe, a protected abbreviation period, or a line that opens a list
# item. ` -- ` is left out: neither corpus uses it, so there is no evidence about it.
_DASH = r"(?<![0-9])(?:\s—\s|—|\s–\s)(?![0-9])"
DASH_FENCE = re.compile(
    rf"(?P<open>{_DASH})"
    r"(?P<mid>(?:(?!\n\s*(?:[-*•]|\d+\.)\s)[^;:|\0—–])+?)"
    rf"(?P<close>{_DASH})"
)
# A line break followed by at most this many words before the closing dash is a
# second "term — gloss" line, not a wrapped interpolation.
GLOSS_LINE_WORDS = 3

AUXILIARY = frozenset({
    "is", "are", "was", "were", "has", "have", "had", "does", "do", "did", "can",
    "cannot", "could", "will", "would", "should", "may", "might", "must", "isn't",
    "aren't", "wasn't", "weren't", "doesn't", "don't", "hasn't", "haven't",
})
FINITE = re.compile(r"^[a-z]+(?:s|ed)$")
# Lists, by suffix and by word, what the `-s`/`-ed` test would otherwise read as a verb.
NOT_VERB_SUFFIX = re.compile(r"(?:ous|less|wards|ness|ies|ss)$")
NOT_VERBS = frozenset({
    "as", "is", "its", "this", "thus", "plus", "yes", "us", "always", "perhaps",
    "sometimes", "unless", "whereas", "regardless", "nonetheless", "besides",
    "afterwards", "indeed", "series", "species", "status", "canvas", "alias",
    "corpus", "axis", "basis", "bias", "bus", "focus", "bonus", "minus", "versus",
    "hundred", "red", "need", "seed", "speed", "feed", "shed", "bed",
})
# A word after one of these is a noun, however it ends: "the tests", "its needs".
DETERMINERS = frozenset({
    "a", "an", "the", "this", "these", "those", "some", "all", "every", "each",
    "any", "no", "its", "their", "our", "my", "your", "his", "her", "both", "few",
    "several", "many", "most", "such", "other", "another", "two", "three", "four",
})
RELATIVIZERS = frozenset({"that", "which", "who", "whose", "whom", "where", "when"})
# A subject that opens with one of these is an adverbial, not a noun phrase, so the
# "verb" after the closing comma is the real subject ("By default, with no config
# file present, findings are printed").
ADVERBIAL_STARTS = frozenset(OPENERS) | frozenset({
    "by", "in", "on", "at", "for", "with", "from", "to", "under", "over", "after",
    "before", "since", "until", "if", "when", "whenever", "once", "unless", "while",
    "as", "here", "there", "otherwise", "today", "then", "now", "still", "also",
    "first", "second", "finally", "meanwhile", "instead", "sometimes", "often",
    "usually", "typically", "normally", "ideally", "again", "above", "below",
    "elsewhere", "off", "optional", "optionally", "note", "so", "yet", "but",
})
MIN_FENCED_WORDS = 4


def _finite(word: str) -> bool:
    w = word.lower()
    if w in AUXILIARY:
        return True
    if word[0].isupper():
        return False  # a capitalised word after a comma is a name, not a verb
    return (FINITE.match(w) is not None and len(w) >= 4
            and w not in NOT_VERBS and NOT_VERB_SUFFIX.search(w) is None)


def _plain_noun_phrase(subject: str) -> bool:
    """Reports whether `subject` reads as a noun phrase rather than a clause or an adverbial.

    A noun phrase carries at most one finite verb per relativizer ("A file that is
    not an image"); a clause carries more, or one with no relativizer at all. A word
    after a determiner is a noun whatever its ending. The first word is not counted
    as a relativizer, since a sentence-initial "Which" is interrogative.
    """
    words = WORD.findall(subject)
    if not words:
        return False
    first = words[0].lower()
    if first in ADVERBIAL_STARTS or first.endswith("ly") or _finite(words[0]):
        return False
    verbs = sum(
        _finite(w) for i, w in enumerate(words)
        if not (i and words[i - 1].lower() in DETERMINERS)
    )
    relativizers = sum(w.lower() in RELATIVIZERS for w in words[1:])
    return verbs <= relativizers


def _sentences(text: str) -> Iterator[tuple[str, int]]:
    """Yields each sentence of the masked text with its offset into `text`."""
    view = masked(text)
    offset = 0
    for sentence in SENTENCE.split(view):
        base = view.find(sentence, offset)
        if base < 0:
            base = offset
        offset = base + len(sentence)
        yield sentence, base


def comma_fenced(text: str) -> list[Span]:
    """Returns every comma-fenced interpolation in `text` that splits a noun phrase from its verb."""
    out: list[Span] = []
    for sentence, base in _sentences(text):
        for m in COMMA_FENCE.finditer(sentence):
            if len(WORD.findall(m.group("fenced"))) < MIN_FENCED_WORDS:
                continue
            if not _finite(m.group("after")):
                continue
            if not _plain_noun_phrase(m.group("subject")):
                continue
            start = base + m.start("fenced") - 2
            end = base + m.end("fenced") + 1
            out.append(Span(text[start:end], "", start, end))
    return out


def _is_fence(m: re.Match[str], sentence: str, line_prefix: str) -> bool:
    mid = m.group("mid")
    if "\n" in mid:
        # Two "term — gloss" lines have a short term at the start of each line; a
        # wrapped interpolation has a whole clause before its opening dash. The term is
        # measured from the start of its line, which may precede the sentence.
        opening = sentence[: m.start()].rsplit("\n", 1)
        term = WORD.findall(opening[-1] if len(opening) > 1 else line_prefix + opening[0])
        closing_line = WORD.findall(mid.rsplit("\n", 1)[1])
        if len(term) <= 2 and len(closing_line) <= GLOSS_LINE_WORDS:
            return False
    inner = WORD.findall(mid)
    after = WORD.findall(sentence[m.end():])
    if inner and after and inner[0].lower() == after[0].lower():
        return False  # "argv — then the config — then the defaults" is a sequence
    return True


def dash_fenced(text: str) -> list[Span]:
    """Returns every span fenced by two dashes inside one sentence of `text`."""
    out: list[Span] = []
    view = masked(text)
    for sentence, base in _sentences(text):
        line_prefix = view[view.rfind("\n", 0, base) + 1 : base]
        for m in DASH_FENCE.finditer(sentence):
            if not _is_fence(m, sentence, line_prefix):
                continue
            start = base + m.start() + (1 if m.group("open")[0].isspace() else 0)
            end = base + m.end() - (1 if m.group("close")[-1].isspace() else 0)
            out.append(Span(text[start:end], "", start, end))
    return out
