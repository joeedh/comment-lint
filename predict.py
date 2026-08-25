"""Score a comment against the trained rule taxonomy. Local, no network calls.

Usage: python predict.py "comment text"
   or: python predict.py --file path/to/comment.txt
   or: python predict.py --coverage        (list which rules the model covers)

Each rule has its own decision threshold, calibrated on a held-out split,
because the rare rules produce good rankings at probabilities a flat 0.5
cut would silence. --threshold overrides all of them with one value.
"""
import argparse
import json
import os

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

MODEL_DIR = "model"
MAX_LEN = 96  # must match train.py


def load():
    tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR)
    model = AutoModelForSequenceClassification.from_pretrained(MODEL_DIR)
    model.eval()
    with open(f"{MODEL_DIR}/labels.json", encoding="utf-8") as f:
        labels = json.load(f)
    with open("data/rules.json", encoding="utf-8") as f:
        rule_desc = {r["id"]: r["desc"] for r in json.load(f)["rules"]}

    thresholds = {l: 0.5 for l in labels}
    path = f"{MODEL_DIR}/thresholds.json"
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            thresholds.update(json.load(f))
    return tokenizer, model, labels, rule_desc, thresholds


def score(text, tokenizer, model, labels, thresholds, override=None):
    enc = tokenizer(text, truncation=True, max_length=MAX_LEN, return_tensors="pt")
    with torch.no_grad():
        logits = model(**enc).logits
    probs = torch.sigmoid(logits)[0].tolist()
    hits = []
    for i, l in enumerate(labels):
        cut = override if override is not None else thresholds.get(l, 0.5)
        if probs[i] >= cut:
            hits.append((l, probs[i], cut))
    # rank by how far past its own cut a rule is, so a rare rule at 0.30/0.12
    # outranks a common one at 0.55/0.50 rather than being buried by raw probability
    return sorted(hits, key=lambda x: -(x[1] / x[2] if x[2] > 0 else x[1]))


def print_coverage(rule_desc, thresholds):
    path = f"{MODEL_DIR}/coverage.json"
    if not os.path.exists(path):
        raise SystemExit("no coverage.json; retrain to generate it")
    with open(path, encoding="utf-8") as f:
        cov = json.load(f)

    # a threshold above 1 means the rule trained but never reached usable
    # precision, so it is switched off rather than shipped as noise
    live = [r for r in cov["trained"] if thresholds.get(r, 0.5) <= 1.0]
    off = [r for r in cov["trained"] if thresholds.get(r, 0.5) > 1.0]

    print(f"ACTIVE ({len(live)} rules -- these can be flagged):")
    for r in live:
        print(f"  {r:5s} cut {thresholds.get(r, 0.5):.2f}  {rule_desc.get(r, '')[:80]}")
    if off:
        print(f"\nOFF ({len(off)} rules -- trained, but too imprecise to ship):")
        for r in off:
            print(f"  {r:5s} {rule_desc.get(r, '')[:85]}")
    print(f"\nUNTRAINED ({len(cov['untrained'])} rules -- never flagged, too few examples):")
    for r, n in cov["untrained"].items():
        print(f"  {r:5s} ({n} examples) {rule_desc.get(r, '')[:75]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("text", nargs="?")
    ap.add_argument("--file")
    ap.add_argument("--threshold", type=float, help="override every per-rule calibrated threshold")
    ap.add_argument("--coverage", action="store_true", help="list covered and uncovered rules, then exit")
    ap.add_argument("--all", action="store_true", help="print every rule's probability, not just hits")
    args = ap.parse_args()

    tokenizer, model, labels, rule_desc, thresholds = load()

    if args.coverage:
        print_coverage(rule_desc, thresholds)
        return

    text = args.text
    if args.file:
        with open(args.file, encoding="utf-8") as f:
            text = f.read()
    if not text:
        raise SystemExit("provide comment text, --file, or --coverage")

    if args.all:
        for rule_id, prob, _ in score(text, tokenizer, model, labels, thresholds, override=0.0):
            cut = args.threshold if args.threshold is not None else thresholds.get(rule_id, 0.5)
            mark = "HIT " if prob >= cut else "    "
            print(f"{mark}{rule_id:5s} {prob:.2f} (cut {cut:.2f})  {rule_desc.get(rule_id, '')[:70]}")
        return

    hits = score(text, tokenizer, model, labels, thresholds, args.threshold)
    if not hits:
        print("clean (no rule above its threshold)")
    for rule_id, prob, cut in hits:
        print(f"{rule_id}  {prob:.2f} (cut {cut:.2f})  {rule_desc.get(rule_id, '')}")


if __name__ == "__main__":
    main()
