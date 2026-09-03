"""Rule P14's deterministic checker for one sub-case of the supporting-premise defect.

P14 says a clause that only supports a following `so` conclusion must be bracketed or
attached as a relative clause rather than coordinated with `and`. The general defect is
undetectable by structure: a gloss about the first clause's object reads exactly like a
correctly coordinated peer premise. docs/research/p14-bracket-supporting-premise.md
measures that and stops.

One sub-case is detectable. When the first clause is a copular statement about its
subject and the coordinated clause's subject is a bare pronoun, the pronoun continues
that subject whichever side of the copula it points at, and the second clause is a
rider that belongs inside the first:

    `Building the playable is the question, and it is pure and writes nothing, so ...`
    `Art notes are the only thing an author says, and they are authored input, so ...`

The examples sit in backticks so that this docstring does not flag itself. Against 92
hand-labelled chains this predicate fires 3 times, all defects. Every filter
below exists to keep a specific false positive silent, and where the text is ambiguous
the checker does not fire, because the finding is a hard failure rather than advice.
The plan is docs/plans/p14-deterministic-checker.md.

This module uses regular expressions only and imports no model backend.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .comments import sentences as sentences_mod

RULE = "P14"

# Hashed into the cache run key, so a change to the predicate invalidates stored
# findings without waiting for a release.
CHECK_VERSION = 4

SENTENCE = re.compile(r"(?<=[.!?])\s+|\n\s*\n")
# The span admits no comma, colon, semicolon or period, and no protected period
# either (a placeholder stands in for one after `sentences.protect`).
CHAIN = re.compile(r",\s+and\s+(?P<mid>[^,:;.\0]{8,120}),\s+so\b")
WORD = re.compile(r"[A-Za-z][A-Za-z'_.-]*")
DASH = re.compile(r"—|–|\s--\s")
# A code span may wrap across lines inside a comment; the cap keeps a stray
# backtick from blanking the rest of the text.
CODE_SPAN = re.compile(r"`[^`]{0,200}`")
QUOTED = re.compile(r'"[^"\n]{1,120}"')
SENTENCE_END = re.compile(r"[.!?]\s")

# Matches a clause boundary inside a sentence; the first clause is what follows the
# last one. A subordinate clause that opens the sentence is cut off separately.
CLAUSE_CUT = re.compile(
    r"(?::|;|—|–|\s--\s"
    r"|,\s+(?:and|but|or|because|since|so|which|whose|while|although|though|if|when|unless)\b"
    r"|\b(?:because|since|while|whereas|unless|although)\b)"
)
LEADING_SUBORDINATE = re.compile(
    r"^\s*(?:when|whenever|if|because|since|while|although|though|unless|after|before|"
    r"once|where|as|until)\b[^,]*,\s*",
    re.I,
)

# The first clause's subject is cut at its first copula. Only a copular first clause
# is accepted: in "X is Y, and it ..." the pronoun continues X whether it points at X
# or at Y, while after a transitive verb it may point at the object instead.
COPULA = frozenset({"is", "are", "was", "were", "isn't", "aren't", "wasn't", "weren't"})
# Auxiliaries and closed verbs, used to find where a subject ends and to recognise
# the verb that must follow the pronoun.
AUXILIARY = COPULA | frozenset({
    "has", "have", "had", "does", "do", "did", "can", "cannot", "could", "will",
    "would", "should", "may", "might", "must", "hasn't", "haven't", "doesn't",
    "don't", "won't", "can't", "couldn't", "wouldn't", "shouldn't",
})
VERBISH = AUXILIARY | frozenset({
    "be", "been", "being", "gets", "get", "got", "goes", "go", "comes", "come",
    "makes", "make", "takes", "take", "needs", "need", "wants", "want",
    "means", "mean", "sits", "sit", "runs", "run", "lives", "live",
    "returns", "return", "holds", "hold", "keeps", "keep", "carries", "carry",
    "belongs", "belong", "stays", "stay", "leaves", "leave", "fires", "fire",
    "reads", "read", "writes", "write", "owns", "own", "knows", "know",
})
FINITE = re.compile(r"^[a-z]+(?:s|ed)$")
# Lists the adverbs that may sit between the pronoun and its verb, as in "it still runs".
ADVERBS = frozenset({
    "still", "also", "then", "never", "only", "always", "already", "now", "just",
    "therefore", "otherwise", "simply", "merely", "too", "even", "later", "first",
})
PREPOSITIONS = frozenset({
    "of", "in", "on", "at", "for", "with", "from", "to", "by", "under", "over",
    "into", "onto", "behind", "beside", "between", "within", "without", "inside",
    "near", "across", "through", "above", "below", "against", "per", "via",
})

# `this`, `these` and `those` are left out. In a code comment they are deictic far
# more often than anaphoric ("and this is where the old name last appears").
SINGULAR = frozenset({"it"})
PLURAL = frozenset({"they", "each", "neither", "both", "none"})
# These four double as determiners ("each process owns"), so after them only an
# auxiliary counts as the verb; a plural noun would pass the finite-verb test.
DETERMINER_LIKE = frozenset({"each", "neither", "both", "none"})
PRONOUNS = SINGULAR | PLURAL

# A first clause whose subject is one of these names no noun for the pronoun to
# continue, so the pronoun points at an object instead.
NO_ANTECEDENT = PRONOUNS | frozenset({
    "this", "these", "those", "there", "what", "that", "which", "who",
    "nothing", "everything", "something", "anything", "nobody", "everybody",
    "somebody", "anybody", "everyone", "someone", "anyone", "one",
})

# Matches expletive and cleft `it`, which continues nothing: "it is safe to", "it is
# not clear why", "it turns out", "it is the caller who". The copula may be followed
# by a negation or an adverb before the adjective or the clause marker.
EXPLETIVE = re.compile(
    r"^it\s+(?:"
    r"(?:is|was|isn't|wasn't|seems|seemed|remains|remained|becomes|became|feels|felt|"
    r"looks|looked|gets|got)\s+(?:(?:not|never|also|still|now|only|just|often|always)\s+)*"
    r"(?:(?:a|an|the)\s+)?(?:[a-z'’-]+\s+){0,2}(?:to|that|whether|which|who|what|why|where|how|when|if|for)\b"
    r"|(?:is|was|isn't|wasn't)\s+(?:(?:not|never|also|still|now|only|just)\s+)*"
    r"(?:clear|unclear|fine|safe|unsafe|hard|harder|easy|easier|cheap|cheaper|expensive|"
    r"wrong|right|better|worse|best|worst|possible|impossible|likely|unlikely|tempting|"
    r"important|enough|ok|okay|true|false|obvious|rare|common|normal|unusual|useful|"
    r"useless|pointless|worth|tricky|simple|simpler|difficult|convenient|necessary|"
    r"sufficient|reasonable|natural|surprising|unfortunate|odd|late|early|time)\b"
    r"|turns\s+out|seems|appears|happens|takes|matters|helps|depends|follows|suffices|"
    r"makes\s+(?:no\s+)?sense|does\s+not\s+matter|doesn't\s+matter|pays\s+to|rains"
    r")",
    re.I,
)

STOP = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from", "has",
    "have", "in", "is", "it", "its", "of", "on", "or", "so", "than", "that",
    "the", "to", "was", "which", "with", "not", "no", "this", "there", "when",
    "where", "what", "would", "can", "cannot", "does", "do", "if", "into",
    "only", "own", "same", "still", "up", "all", "any", "how", "why", "who",
})


@dataclass(frozen=True)
class Span:
    """Records one firing: the `, and ..., so` text and the pronoun that opened its clause."""

    clause: str
    pronoun: str
    start: int
    end: int


def _copular_subject(clause: str) -> list[str] | None:
    """Returns the words before the clause's copula, or None when its verb is not one.

    The subject is cut at the first preposition as well, so "The list of handlers"
    has the head "list" rather than "handlers".
    """
    words = WORD.findall(clause)
    for i, w in enumerate(words):
        if w.lower() in COPULA:
            subject = words[:i]
            break
        if w.lower() in VERBISH or i >= 8:
            return None
    else:
        return None
    if not subject:
        return None
    after = [w.lower() for w in words[i + 1 :] if w.lower() not in ("not", "still", "also", "now")]
    # "The socket is in the pool, and it ..." names a second noun the pronoun could
    # continue, so a copula followed by a preposition is not accepted.
    if after and after[0] in PREPOSITIONS:
        return None
    for j, w in enumerate(subject):
        if j and w.lower() in PREPOSITIONS:
            return subject[:j]
    return subject


def _plural(subject: list[str]) -> bool:
    if " and " in " ".join(subject).lower():
        return True
    heads = [w for w in subject if w.lower() not in STOP] or subject
    head = heads[-1].lower().strip("`'\"*_")
    return head.endswith("s") and not head.endswith("ss")


def _bare(words: list[str]) -> bool:
    """Reports whether the pronoun is the whole subject, with its verb directly after it."""
    rest = words[1:]
    if rest and rest[0].lower() in ADVERBS:
        rest = rest[1:]
    if not rest:
        return False
    verb = rest[0].lower()
    if words[0].lower() in DETERMINER_LIKE:
        return verb in AUXILIARY
    return verb in VERBISH or FINITE.match(verb) is not None


def _fires(first: str, middle: str) -> str | None:
    """Returns the pronoun that opens `middle` when it continues the subject of `first`."""
    if DASH.search(middle) or "`" in middle:
        return None
    words = WORD.findall(middle)
    if not words or words[0].lower() not in PRONOUNS or not _bare(words):
        return None
    pronoun: str = words[0].lower()
    if pronoun == "it" and EXPLETIVE.match(middle.strip()):
        return None
    clause = LEADING_SUBORDINATE.sub("", CLAUSE_CUT.split(first)[-1].strip(" ,"))
    if pronoun in {w.lower() for w in WORD.findall(clause)}:
        return None
    subject = _copular_subject(clause)
    if not subject or subject[0].lower() in NO_ANTECEDENT:
        return None
    if _plural(subject) != (pronoun in PLURAL):
        return None
    return pronoun


def masked(text: str) -> str:
    """Returns `text` with code spans and quoted strings blanked and abbreviation periods protected.

    The result has the same length as `text`, so offsets found in it index `text`.
    """
    def blank(m: re.Match[str]) -> str:
        # A span that runs past a sentence end is a stray backtick, not code, and
        # blanking it would silence every checker on the sentences it covers.
        if "\n" in m.group(0) and SENTENCE_END.search(m.group(0)):
            return m.group(0)
        return m.group(0)[0] + "x" * (len(m.group(0)) - 2) + m.group(0)[-1]

    return sentences_mod.protect(QUOTED.sub(blank, CODE_SPAN.sub(blank, text)))


def supporting_premise(text: str) -> list[Span]:
    """Returns every `, and <pronoun> ..., so` chain in `text` whose pronoun continues the subject."""
    out: list[Span] = []
    view = masked(text)
    offset = 0
    for sentence in SENTENCE.split(view):
        base = view.find(sentence, offset)
        if base < 0:
            base = offset
        offset = base + len(sentence)
        for m in CHAIN.finditer(sentence):
            pronoun = _fires(sentence[: m.start()], m.group("mid"))
            if pronoun is not None:
                start, end = base + m.start(), base + m.end()
                out.append(Span(text[start:end], pronoun, start, end))
    return out
