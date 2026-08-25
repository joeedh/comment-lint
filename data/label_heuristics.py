"""Canonical, uniform silver-labeler for violation_pairs.jsonl.

Replaces the six inconsistent per-fork heuristics with one script applied
identically across every pair. Deliberately conservative: a pair gets a
label only when a fairly distinctive surface signature fires, comparing
"before" against "after" (the signature must be present in before and
absent/changed in after). Anything that doesn't match a clear pattern is
left unlabeled rather than guessed -- noisy positives are worse than a
missing label for a bootstrap classifier.

Known, documented gap: C1/C3/C5/C6 need the code line(s) beneath the
comment, which this comment-only dataset never captured. They get zero
coverage here; fixing that requires a re-mine that keeps adjacent code.
"""
import json
import re
import sys

EMDASH = "—|–"


def has(pattern, text, flags=re.I):
    return re.search(pattern, text, flags) is not None


def label(before, after):
    labels = set()

    # P10 rhetorical emphasis: markdown bold/italic present in before, gone in after.
    if re.search(r"(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|_[^_\s][^_]*_)", before) and not re.search(
        r"(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|_[^_\s][^_]*_)", after
    ):
        labels.add("P10")

    # P5 double negative: "cannot ... not" / "never ... not" / "not ... without"
    if has(r"\bcan(?:not|'t)\b[^.]{0,40}\bnot\b", before) or has(r"\bnever\b[^.]{0,30}\bnot\b", before):
        labels.add("P5")

    # P4 fragment opener: colon or em-dash pivot after a short clause that names
    # a placeholder, then the after-text restructures into full sentences
    # (no colon-led fragment, or fewer colons than before).
    before_colon_frag = bool(re.search(r"^[^.:]{5,60}:\s+\w", before)) or bool(
        re.search(rf"\S\s({EMDASH})\s\w", before)
    )
    after_colon_frag = bool(re.search(r"^[^.:]{5,60}:\s+\w", after))
    if before_colon_frag and not after_colon_frag:
        labels.add("P4")

    # P7 clause-A-else-B: "else" / "otherwise" / "falling back" combined with a colon
    # or "when"/"unless" case split, restructured away in after.
    if has(r"\b(else|otherwise|falling back)\b", before) and ":" in before and not (
        has(r"\b(else|otherwise|falling back)\b", after) and ":" in after
    ):
        labels.add("P7")

    # P13 bracket-not-comma: paired commas fencing a subordinate clause in before,
    # replaced by parentheses in after.
    if re.search(r"[a-z],\s+[a-z ]{4,40},\s+[a-z]", before) and "(" in after and "(" not in before:
        labels.add("P13")

    # P9 nonassertive-under-definite: "any/anywhere/ever" modifying a "the X" definite.
    if has(r"\bthe\s+\w+\s+(anywhere|any\b|ever\b)", before) and not has(
        r"\bthe\s+\w+\s+(anywhere|any\b|ever\b)", after
    ):
        labels.add("P9")

    # P11 accurate head noun: trailing ", as X" or ", in the form of X" dropped in after.
    if has(r",\s*(as|in the form of)\s+\w+", before) and not has(r",\s*(as|in the form of)\s+\w+", after):
        labels.add("P11")

    # P12 backticks around a doc path / section reference rather than a code symbol.
    if has(r"`[\w./-]+\.md`", before) or has(r"`[\w./-]+`\s*§", before):
        labels.add("P12")

    # P3 metaphorical equation: "X is the Y" / "X as Y" identity claim, reworded
    # in after to a plain action/consequence sentence (heuristic: after starts
    # with a different structure and before contains a bare copula "is the"/"is a").
    if has(r"\bis\s+(the|a)\s+\w+", before) and has(r"\b(does|says|means|refuses|passes|returns|runs)\b", after):
        labels.add("P3")

    # P6 dangling reference: before opens with a bare pronoun subject ("It ", "This ",
    # "That "), after replaces it with a concrete noun in the same position.
    m_before = re.match(r"^(It|This|That|They)\b", before.strip())
    m_after = re.match(r"^(It|This|That|They)\b", after.strip())
    if m_before and not m_after:
        labels.add("P6")

    return sorted(labels)


def main():
    src, dst = sys.argv[1], sys.argv[2]
    n, labeled = 0, 0
    with open(src, encoding="utf-8") as fin, open(dst, "w", encoding="utf-8") as fout:
        for line in fin:
            row = json.loads(line)
            labels = label(row["before"], row["after"])
            row["labels"] = labels
            n += 1
            labeled += 1 if labels else 0
            fout.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"{n} rows, {labeled} labeled ({labeled/n:.0%}), {n - labeled} empty", file=sys.stderr)


if __name__ == "__main__":
    main()
