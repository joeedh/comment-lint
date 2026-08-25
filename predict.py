"""Score a comment against the trained rule taxonomy. Local, no network calls.

Usage: python predict.py "comment text"
   or: python predict.py --file path/to/comment.txt
   or: python predict.py --coverage        (list which rules the model covers)

Verdicts come in two stages. A gate decides whether the comment violates
anything at all, then the per-rule heads are ranked against each other to say
which rule it most likely breaks. The ranking is the useful half: a rule that
fires on 5% of comments puts mostly negatives at the top of its own corpus-wide
ranking even at a respectable AUC, whereas asking which of 16 rules best
explains one suspect comment lands a true rule in the top 3 87% of the time.

So a rule listed below the gate's verdict is a ranked suspicion, not an
independent detection. --all prints the raw per-rule probabilities.

Two backends are supported and picked by which one is present, linear first:
model_linear/ (scikit-learn, ships by default) and model/ (fine-tuned encoder).
"""
import argparse
import json
import os

LINEAR_DIR = os.environ.get("CL_MODEL", "model_linear")
ENCODER_DIR = "model"
MAX_LEN = 96  # must match train.py
TOP_K = 3


class LinearBackend:
    """TF-IDF word+char n-grams into one gate head and one head per rule."""

    name = "linear"

    def __init__(self, model_dir):
        from joblib import load

        self.dir = model_dir
        bundle = load(f"{model_dir}/model.joblib")
        self.vec, self.gate, self.heads = bundle["vectorizer"], bundle["gate"], bundle["heads"]
        with open(f"{model_dir}/labels.json", encoding="utf-8") as f:
            self.labels = json.load(f)

    def score(self, text):
        X = self.vec.transform([text])
        gate = float(self.gate.predict_proba(X)[0, 1])
        probs = [float(h.predict_proba(X)[0, 1]) if h is not None else 0.0 for h in self.heads]
        return gate, probs


class EncoderBackend:
    """Fine-tuned bert-mini with a sigmoid head per rule and no gate."""

    name = "encoder"

    def __init__(self, model_dir):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self.torch = torch
        self.dir = model_dir
        self.tokenizer = AutoTokenizer.from_pretrained(model_dir)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_dir)
        self.model.eval()
        with open(f"{model_dir}/labels.json", encoding="utf-8") as f:
            self.labels = json.load(f)

    def score(self, text):
        enc = self.tokenizer(text, truncation=True, max_length=MAX_LEN, return_tensors="pt")
        with self.torch.no_grad():
            logits = self.model(**enc).logits
        probs = self.torch.sigmoid(logits)[0].tolist()
        return None, probs


def load(prefer=None):
    if prefer == "encoder" or (prefer is None and not os.path.exists(f"{LINEAR_DIR}/model.joblib")):
        if not os.path.exists(f"{ENCODER_DIR}/config.json"):
            raise SystemExit(f"no model found in {LINEAR_DIR}/ or {ENCODER_DIR}/; run train_linear.py first")
        backend = EncoderBackend(ENCODER_DIR)
    else:
        backend = LinearBackend(LINEAR_DIR)

    with open("data/rules.json", encoding="utf-8") as f:
        rule_desc = {r["id"]: r["desc"] for r in json.load(f)["rules"]}

    thresholds = {}
    path = f"{backend.dir}/thresholds.json"
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            thresholds = json.load(f)
    return backend, rule_desc, thresholds


def ranked(backend, probs, limit=None):
    order = sorted(range(len(probs)), key=lambda i: -probs[i])
    if limit is not None:
        order = order[:limit]
    return [(backend.labels[i], probs[i]) for i in order]


def print_coverage(backend, rule_desc, thresholds):
    path = f"{backend.dir}/coverage.json"
    if not os.path.exists(path):
        raise SystemExit("no coverage.json; retrain to generate it")
    with open(path, encoding="utf-8") as f:
        cov = json.load(f)

    if "gate" in cov:
        g, a = cov["gate"], cov.get("attribution", {})
        print(f"GATE: cut {g['cut']:.2f}, AUC {g['auc']:.3f} on held-out text")
        if a:
            share = ", ".join(f"top-{k[3:]} {v:.0%}" for k, v in sorted(a.items()))
            print(f"ATTRIBUTION: a true rule is {share}\n")

    print(f"RANKED ({len(cov['trained'])} rules -- these can be named as suspects):")
    for r in cov["trained"]:
        print(f"  {r:5s} {rule_desc.get(r, '')[:85]}")
    print(f"\nUNTRAINED ({len(cov['untrained'])} rules -- never named, too few examples):")
    for r, n in cov["untrained"].items():
        print(f"  {r:5s} ({n} examples) {rule_desc.get(r, '')[:75]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("text", nargs="?")
    ap.add_argument("--file")
    ap.add_argument("--threshold", type=float, help="override the calibrated gate cut")
    ap.add_argument("--top", type=int, default=TOP_K, help=f"how many rules to name (default {TOP_K})")
    ap.add_argument("--coverage", action="store_true", help="list covered and uncovered rules, then exit")
    ap.add_argument("--all", action="store_true", help="print every rule's probability, not just the top ones")
    ap.add_argument("--backend", choices=["linear", "encoder"], help="override backend selection")
    args = ap.parse_args()

    backend, rule_desc, thresholds = load(args.backend)

    if args.coverage:
        print_coverage(backend, rule_desc, thresholds)
        return

    text = args.text
    if args.file:
        with open(args.file, encoding="utf-8") as f:
            text = f.read()
    if not text:
        raise SystemExit("provide comment text, --file, or --coverage")

    gate, probs = backend.score(text)
    cut = args.threshold if args.threshold is not None else thresholds.get("__gate__", 0.5)

    if gate is None:
        print(f"{backend.name} backend has no gate; showing ranked rules only")
    elif gate >= cut:
        print(f"VIOLATION  {gate:.2f} (cut {cut:.2f})")
    else:
        print(f"clean      {gate:.2f} (cut {cut:.2f})")

    for rule_id, prob in ranked(backend, probs, None if args.all else args.top):
        print(f"  {rule_id:5s} {prob:.2f}  {rule_desc.get(rule_id, '')[:90]}")


if __name__ == "__main__":
    main()
