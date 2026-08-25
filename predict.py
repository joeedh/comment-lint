"""Score a comment against the trained rule taxonomy. Local, no network calls.

Usage: python predict.py "comment text" [--threshold 0.5]
   or: python predict.py --file path/to/comment.txt
"""
import argparse
import json

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

MODEL_DIR = "model"


def load():
    tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR)
    model = AutoModelForSequenceClassification.from_pretrained(MODEL_DIR)
    model.eval()
    with open(f"{MODEL_DIR}/labels.json", encoding="utf-8") as f:
        labels = json.load(f)
    with open("data/rules.json", encoding="utf-8") as f:
        rule_desc = {r["id"]: r["desc"] for r in json.load(f)["rules"]}
    return tokenizer, model, labels, rule_desc


def score(text, tokenizer, model, labels, threshold=0.5):
    enc = tokenizer(text, truncation=True, max_length=96, return_tensors="pt")
    with torch.no_grad():
        logits = model(**enc).logits
    probs = torch.sigmoid(logits)[0].tolist()
    return sorted(
        [(labels[i], probs[i]) for i in range(len(labels)) if probs[i] >= threshold],
        key=lambda x: -x[1],
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("text", nargs="?")
    ap.add_argument("--file")
    ap.add_argument("--threshold", type=float, default=0.5)
    args = ap.parse_args()

    text = args.text
    if args.file:
        with open(args.file, encoding="utf-8") as f:
            text = f.read()
    if not text:
        raise SystemExit("provide comment text or --file")

    tokenizer, model, labels, rule_desc = load()
    hits = score(text, tokenizer, model, labels, args.threshold)
    if not hits:
        print("clean (no rule above threshold)")
    for rule_id, prob in hits:
        print(f"{rule_id}  {prob:.2f}  {rule_desc.get(rule_id, '')}")


if __name__ == "__main__":
    main()
