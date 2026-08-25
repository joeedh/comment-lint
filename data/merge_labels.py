"""Merge two independent labelers' output into a consensus training file.

Reads the per-batch outputs written by the labeling agents (out_NN_A.json /
out_NN_B.json), joins them back onto the mined pairs in labeled_all.jsonl, and
writes labeled_all_v2.jsonl.

Each row gains three fields:
  labels          union of both labelers -- what training sees
  labels_agreed   intersection -- what evaluation sees
  agreement       "full" when the two label sets match exactly, "partial" when
                  they overlap without matching, "conflict" when one labeler
                  found a violation and the other found none

The union/intersection split exists because the two labelers agree on whether a
comment is bad far more often than on which of the overlapping prose rules it
breaks. Training on the union keeps that signal; scoring only on agreed items
keeps the metric off items two careful readers genuinely split on.

Usage: python data/merge_labels.py <relabel_dir> [out_path]
"""
import glob
import json
import os
import sys
from collections import Counter

SRC = "data/labeled_all.jsonl"


def load_labeler_outputs(relabel_dir):
    """Return {item_index: (labels_A, labels_B)} for every doubly-labeled item."""
    out = {}
    for pa in sorted(glob.glob(os.path.join(relabel_dir, "out_*_A.json"))):
        pb = pa.replace("_A.json", "_B.json")
        if not os.path.exists(pb):
            print(f"skipping {os.path.basename(pa)}: no B counterpart", file=sys.stderr)
            continue
        with open(pa, encoding="utf-8") as f:
            A = {r["i"]: set(r["labels"]) for r in json.load(f)}
        with open(pb, encoding="utf-8") as f:
            B = {r["i"]: set(r["labels"]) for r in json.load(f)}
        for i in A:
            if i in B:
                out[i] = (A[i], B[i])
    return out


def agreement_kind(a, b):
    if a == b:
        return "full"
    if a & b:
        return "partial"
    return "conflict"


def main():
    relabel_dir = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else "data/labeled_all_v2.jsonl"

    with open(SRC, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f]
    labeled = load_labeler_outputs(relabel_dir)

    kinds, rule_counts = Counter(), Counter()
    n_recovered = 0
    for i, row in enumerate(rows):
        if i in labeled:
            a, b = labeled[i]
            union, inter = sorted(a | b), sorted(a & b)
            row["labels"] = union
            row["labels_agreed"] = inter
            row["agreement"] = agreement_kind(a, b)
            row["source"] = "agent"
            kinds[row["agreement"]] += 1
            rule_counts.update(union)
            if union:
                n_recovered += 1
        else:
            # heuristic rows keep their labels and are treated as self-agreeing
            row["labels_agreed"] = row.get("labels", [])
            row["agreement"] = "full"
            row["source"] = row.get("source", "heuristic")
            rule_counts.update(row.get("labels", []))

    with open(dst, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"wrote {dst}: {len(rows)} rows, {len(labeled)} agent-labeled", file=sys.stderr)
    print(f"  agreement: {dict(kinds)}", file=sys.stderr)
    print(f"  recovered {n_recovered} positives that were previously all-zero negatives", file=sys.stderr)
    print("\nper-rule totals (union):", file=sys.stderr)
    for r, c in sorted(rule_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {r:5s} {c}", file=sys.stderr)


if __name__ == "__main__":
    main()
