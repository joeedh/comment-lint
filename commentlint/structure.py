"""Clause-structure features for rules whose evidence is a configuration.

P14 moves `and`, a comma and a bracket, which are the most common tokens in the
corpus, so tf-idf gives them almost no weight and a bag of n-grams puts a repair
0.04 away from the defect it fixes. What tells the two apart is where those
tokens sit relative to each other, which a bag has no way to represent.

Two families, both computed from a single comment so they are available at
predict time:

  A  the sequence of connectives in a sentence, as n-grams, so "..., and ...,
     so ..." is one feature rather than four unweighted unigrams
  B  whether the middle conjunct points back into the clause before it, which
     is what separates a subordinate premise from a peer one

Used by train_linear.py behind CL_STRUCT=1. Not shipped in the model yet.

Measured over 12 reseeded splits with the 20 pairs of data/p14_pairs.jsonl
injected, A and B move P14 attribution from 0% to 85% top-1 and the before/after
cosine distance from 0.040 to 0.357. They do not move the gate (6 of 33 P14
comments called bad, unchanged), because the chain shape is not evidence of a
defect -- correct prose coordinates two peer premises the same way.

A deterministic checker over the same shape ships as commentlint/premise.py for
one sub-case, a copular first clause followed by a coordinated clause whose
subject is a bare pronoun. On the 5998 untouched comments of
data/clean_comments.jsonl the shape matches 92 times, 12 of those are the defect,
and the checker fires on 3 of the 12 with no false positive. A dependency parse
reached 5 of 12 and was declined for its cost; no regex predicate reaches the
rest. See docs/research/p14-bracket-supporting-premise.md.

A third family was tried and removed: a lexical window either side of the
connective, plus given/new (whether the middle conjunct is built from terms the
comment already introduced), the definiteness of its subject, and where the
back-reference falls inside it. It reached precision 0.10 against a 0.50 floor,
against 0.07 for A and B alone, which is inside seed noise. Adding 19
peer-premise comments as hard negatives made it worse, not better: precision
0.03, because the features cannot separate a gloss from an independent premise,
so suppressing the shape suppresses the true positives with it.
"""
import re
from typing import Iterable

# Ordered so a longer marker wins: ", and" must be found before the bare comma.
CONNECTIVES = [
    ("AND", r",\s+and\b"),
    ("BUT", r",\s+but\b"),
    ("OR", r",\s+or\b"),
    ("SO", r",\s+so\b"),
    ("WHICH", r",\s+wh(?:ich|ose|o)\b"),
    ("BECAUSE", r",\s+(?:because|since)\b"),
    ("RPAREN", r"\)"),
    ("LPAREN", r"\("),
    ("DASH", r"\s(?:—|–|--)\s"),
    ("COLON", r":"),
    ("SEMI", r";"),
]
MARKER = re.compile("|".join(f"(?P<{name}>{pat})" for name, pat in CONNECTIVES))
SENTENCE = re.compile(r"(?<=[.!?])\s+|\n\s*\n")

PRONOUNS = {"it", "they", "them", "each", "that", "those", "this", "these", "one", "both"}
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from", "has", "have",
    "in", "is", "it", "its", "of", "on", "or", "so", "than", "that", "the", "to", "was",
    "which", "with", "not", "no", "this", "there", "when", "where", "what", "would",
    "can", "cannot", "does", "do", "if", "into", "only", "own", "same", "still", "up",
}
WORD = re.compile(r"[A-Za-z][A-Za-z'_.-]*")


def _content(text: str) -> set[str]:
    return {w.lower() for w in WORD.findall(text) if w.lower() not in STOPWORDS and len(w) > 2}


def _backref(before: str, middle: str) -> Iterable[str]:
    """Family B: does the middle conjunct predicate about a noun in the clause before it."""
    overlap = len(_content(before) & _content(middle))
    yield f"bref:{min(overlap, 2)}"
    words = WORD.findall(middle)
    if words and words[0].lower() in PRONOUNS:
        yield "bsubj:pron"
    if words and len(words) < len(WORD.findall(before)):
        yield "bshort"


def _emit(text: str) -> list[str]:
    out: list[str] = []
    for sentence in SENTENCE.split(text):
        marks = [(m.lastgroup or "?", m.start(), m.end()) for m in MARKER.finditer(sentence)]
        if not marks:
            continue
        names = [m[0] for m in marks]
        for i in range(len(names) - 1):
            out.append(f"c2:{names[i]}>{names[i + 1]}")
        for i in range(len(names) - 2):
            out.append(f"c3:{names[i]}>{names[i + 1]}>{names[i + 2]}")

        # Family B, on every conjunct that sits directly in front of a "so".
        for i in range(len(names) - 1):
            if names[i + 1] != "SO" or names[i] not in ("AND", "WHICH", "RPAREN", "DASH"):
                continue
            kind = names[i]
            # A bracketed premise opens at its "(", so the clause it qualifies
            # is what runs up to that, not the parenthetical itself.
            head = i - 1 if kind == "RPAREN" and i and names[i - 1] == "LPAREN" else i
            opener = marks[head - 1][2] if head else 0
            before = sentence[opener : marks[head][1]]
            middle = sentence[marks[head][2] : marks[i + 1][1]]
            for f in _backref(before, middle):
                out.append(f"{kind}:{f}")
            out.append(f"premise:{kind}")
    return out


def tokens(text: str) -> list[str]:
    """Feature tokens for one comment. The analyzer TfidfVectorizer is handed."""
    return _emit(text)
