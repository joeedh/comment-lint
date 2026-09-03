"""Reproduces the tables in docs/research/p13-comma-and-dash-interpolation.md.

Run from the repository root: `python data/p13_pairs_eval.py`. Prints what the 21
P13-labelled pairs in labeled_all_v2.jsonl actually changed, what the author's
revisions did with a dash-fenced interpolation under the shipped P15 predicate, and
the two checkers' firing counts on the clean corpus.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from commentlint import interpolation as interp  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
# The silver heuristic's comma shape, widened from 40 to 80 characters so the one
# long revision-confirmed comma defect is classified rather than left as "something else".
LOOSE_COMMA = re.compile(r"[a-z],\s+[a-z ]{4,80},\s+[a-z]")
HYPHEN_FENCE = re.compile(r"\s-\s[^.;:]+\s-\s")


def rows(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def gained_parens(r):
    return r["after"].count("(") > r["before"].count("(")


def labelled_pairs():
    counts = {"dash -> parentheses": 0, "comma -> parentheses": 0,
              "comma -> commas dropped": 0, "spaced hyphens -> parentheses": 0,
              "something else": 0}
    for r in rows("labeled_all_v2.jsonl"):
        if "P13" not in r["labels"]:
            continue
        comma = LOOSE_COMMA.search(r["before"]) is not None
        if interp.dash_fenced(r["before"]) and gained_parens(r):
            counts["dash -> parentheses"] += 1
        elif HYPHEN_FENCE.search(r["before"]) and gained_parens(r):
            counts["spaced hyphens -> parentheses"] += 1
        elif comma and gained_parens(r):
            counts["comma -> parentheses"] += 1
        elif comma and not LOOSE_COMMA.search(r["after"]):
            counts["comma -> commas dropped"] += 1
        else:
            counts["something else"] += 1
    print("P13-labelled pairs, by what the revision changed")
    for k, v in counts.items():
        print(f"  {k:30} {v}")


def dash_revisions():
    kept = parens = rewritten = 0
    for r in rows("violation_pairs.jsonl"):
        before = len(interp.dash_fenced(r["before"]))
        if not before:
            continue
        if len(interp.dash_fenced(r["after"])) >= before:
            kept += 1
        elif gained_parens(r):
            parens += 1
        else:
            rewritten += 1
    total = kept + parens + rewritten
    print(f"dash fences in revision before-texts: {total}")
    for k, v in (("replaced by parentheses", parens), ("rewritten away", rewritten), ("kept", kept)):
        print(f"  {k:24} {v:4} {100 * v / total:.0f}%")


def clean_corpus():
    clean = rows("clean_comments.jsonl")
    comma = [i for i, r in enumerate(clean) if interp.comma_fenced(r["comment"])]
    dash = [len(interp.dash_fenced(r["comment"])) for r in clean]
    print(f"clean corpus, {len(clean)} comments")
    print(f"  P13 comments {len(comma)} {comma}")
    print(f"  P15 comments {sum(1 for n in dash if n)} spans {sum(dash)}")


if __name__ == "__main__":
    labelled_pairs()
    dash_revisions()
    clean_corpus()
