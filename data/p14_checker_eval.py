"""Reproduces the attempt-5 tables of
docs/research/p14-bracket-supporting-premise.md.

Run from the repository root:  python data/p14_checker_eval.py

Extracts every "A, and B, so C" chain from data/clean_comments.jsonl, scores a
set of candidate predicates against the hand labels below, and prints the two
tables the report quotes, with one row added for the predicate that shipped as
commentlint/premise.py. Nothing here is imported by the package; it is the evidence
for what the checker fires on and for the rest of P14 having no checker.
"""
import json
import random
import re
import statistics
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from commentlint import premise  # noqa: E402

SENTENCE = re.compile(r"(?<=[.!?])\s+|\n\s*\n")
CHAIN = re.compile(r",\s+and\s+(?P<mid>[^,]{8,120}),\s+so\b")
WORD = re.compile(r"[A-Za-z][A-Za-z'_.-]*")
DASH = re.compile(r"(?:—|–|\s--\s)")
FINITE = re.compile(r"\b[a-z][a-z]*(?:s|ed)\b")

# Cuts the subject at the first verb. A closed list, so it under-cuts on a
# conjunct that opens with an adjunct; the report says what would replace it.
VERBISH = {
    "is", "are", "was", "were", "be", "been", "being", "has", "have", "had",
    "does", "do", "did", "can", "cannot", "could", "will", "would", "should",
    "may", "might", "must", "isn't", "aren't", "wasn't", "doesn't", "don't",
    "won't", "can't", "gets", "get", "got", "goes", "go", "comes", "come",
    "makes", "make", "takes", "take", "needs", "need", "wants", "want",
    "means", "mean", "sits", "sit", "runs", "run", "lives", "live",
    "returns", "return", "holds", "hold", "keeps", "keep", "carries", "carry",
    "belongs", "belong", "stays", "stay", "leaves", "leave", "fires", "fire",
    "reads", "read", "writes", "write", "owns", "own", "knows", "know",
}
ANAPHORS = {"it", "its", "they", "them", "their", "each", "this", "these", "those"}
BARE = {"it", "they", "this", "these", "those", "each", "neither", "both", "one"}
STOP = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from", "has",
    "have", "in", "is", "it", "its", "of", "on", "or", "so", "than", "that",
    "the", "to", "was", "which", "with", "not", "no", "this", "there", "when",
    "where", "what", "would", "can", "cannot", "does", "do", "if", "into",
    "only", "own", "same", "still", "up", "all", "any", "how", "why", "who",
}

# Hand labels for the 92 matches, in extraction order. One annotator, so this is
# a single reading rather than adjudicated ground truth. D marks a gloss
# coordinated as a peer premise, A marks a match that is not a two-premise chain
# (a three-item list, coordinated verb phrases, or a span crossing an em dash),
# and everything else is a correctly coordinated peer premise.
DEFECT = {2, 9, 25, 32, 35, 36, 43, 64, 76, 78, 79, 82}
ARTIFACT = {3, 6, 8, 15, 20, 21, 22, 24, 29, 44, 45, 46, 47, 49, 51, 54, 58, 59,
            60, 63, 65, 66, 68, 70, 72, 73, 74, 77, 81, 86, 87, 89, 91}


def subject(middle: str) -> list[str]:
    out: list[str] = []
    for w in WORD.findall(middle):
        if w.lower() in VERBISH or len(out) >= 6:
            break
        out.append(w)
    return out


def content(words) -> set[str]:
    return {w.lower() for w in words if w.lower() not in STOP and len(w) > 2}


def chains(text: str):
    for sentence in SENTENCE.split(text):
        for m in CHAIN.finditer(sentence):
            yield {"text": text, "head": sentence[: m.start()],
                   "middle": m.group("mid"), "subject": subject(m.group("mid"))}


def binary(h) -> bool:
    """Two coordinated clauses, rather than a list or a shared subject."""
    if DASH.search(h["middle"]) or DASH.search(h["head"]):
        return False
    words = WORD.findall(h["middle"])
    if not words:
        return False
    # A conjunct with no finite verb of its own is a coordinated phrase.
    if not ({w.lower() for w in words} & VERBISH or FINITE.search(h["middle"].lower())):
        return False
    # A comma in the first premise with no conjunction after it separates list
    # items, so the "and" closes a list rather than joining two premises.
    for m in re.finditer(r",\s+(?!(?:and|but|or|so|which|because|since|whose|who)\b)", h["head"]):
        if WORD.findall(h["head"][m.end():]):
            return False
    return True


def anaphor(h) -> bool:
    return bool(h["subject"]) and h["subject"][0].lower() in ANAPHORS


def given(h, head_noun_only: bool = False) -> bool:
    if not h["subject"]:
        return False
    prior = content(WORD.findall(h["text"][: h["text"].find(h["middle"])]))
    subj = h["subject"][-1:] if head_noun_only else h["subject"]
    return bool(content(subj) & prior)


def bare_pron(h) -> bool:
    return len(h["subject"]) == 1 and h["subject"][0].lower() in BARE


PREDICATES = {
    "shape only": lambda h: True,
    "+ binary-chain filter": binary,
    "given subject, any content word": lambda h: given(h),
    "given subject, head noun only": lambda h: given(h, True),
    "anaphoric subject": anaphor,
    "anaphoric or given": lambda h: anaphor(h) or given(h),
    "bare-pronoun subject": bare_pron,
    "bare pronoun or short anaphoric": lambda h: bare_pron(h) or (
        len(WORD.findall(h["middle"])) <= 7 and anaphor(h)),
    # The shipped checker, run on the whole comment so that its own masking and
    # span rules apply, then matched back to this chain. commentlint/premise.py.
    "shipped: copular subject continuation": lambda h: any(
        " ".join(h["middle"].split()) in " ".join(s.clause.split())
        for s in premise.supporting_premise(h["text"])),
}


def label(i: int) -> str:
    return "D" if i in DEFECT else "A" if i in ARTIFACT else "P"


def score(pred, hits, ids):
    tp = fp = fn = 0
    for i in ids:
        fired, defect = bool(pred(hits[i])), label(i) == "D"
        tp += fired and defect
        fp += fired and not defect
        fn += not fired and defect
    return tp, fp, fn


def main() -> int:
    rows = [json.loads(l) for l in open("data/clean_comments.jsonl", encoding="utf8")]
    hits = [c for r in rows for c in chains(r["comment"])]
    if len(hits) != 92:
        print(f"corpus moved: {len(hits)} chains, but the labels cover 92", file=sys.stderr)
        return 1
    ids = list(range(len(hits)))
    counts = {k: sum(1 for i in ids if label(i) == k) for k in "DPA"}
    print(f"{len(rows)} comments, {len(hits)} chains in "
          f"{len({h['head'] for h in hits})} comments\n"
          f"defect {counts['D']}  peer {counts['P']}  artifact {counts['A']}"
          f"   base rate {counts['D'] / len(hits):.2f}\n")

    print(f"{'predicate':34s} {'fires':>5s} {'TP':>3s} {'FP':>3s} {'prec':>5s} {'recall':>7s}")
    for name, pred in PREDICATES.items():
        tp, fp, fn = score(pred, hits, ids)
        prec = tp / (tp + fp) if tp + fp else float("nan")
        print(f"{name:34s} {tp + fp:5d} {tp:3d} {fp:3d} {prec:5.2f} {tp / (tp + fn):7.0%}")

    print("\nsplit-half over 200 reseeds (the predicates are fixed, so this is"
          " sampling noise, not generalisation)")
    for name in ("anaphoric subject", "bare-pronoun subject",
                 "bare pronoun or short anaphoric", "shipped: copular subject continuation"):
        pred, precs = PREDICATES[name], []
        rnd = random.Random(0)
        for _ in range(200):
            shuffled = ids[:]
            rnd.shuffle(shuffled)
            tp, fp, _ = score(pred, hits, shuffled[len(ids) // 2:])
            if tp + fp:
                precs.append(tp / (tp + fp))
        precs.sort()
        print(f"{name:34s} precision median {statistics.median(precs):.2f}"
              f"  5-95% [{precs[len(precs) // 20]:.2f}, {precs[-len(precs) // 20]:.2f}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
