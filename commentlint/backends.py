"""Model loading and scoring. The only module that imports sklearn or torch.

Keeping that import here, and importing this module lazily, is what makes a
fully cached run fast: `import sklearn` costs 2.41s of the 2.81s it takes to
load the model at all. A cached run that never scores anything must never
reach this file.

Scoring is batched because batching is 8x faster than one call per comment
(0.093s vs 0.71s for 500), which at scan scale dominates everything else the
model path does.
"""
import json
import os

from . import ENCODER_DIR, LINEAR_DIR, RULES_PATH

MAX_LEN = 96  # must match train.py


class LinearBackend:
    """TF-IDF word+char n-grams into one gate head and one head per rule."""

    name = "linear"
    has_gate = True

    def __init__(self, model_dir=None):
        from joblib import load

        self.dir = model_dir or LINEAR_DIR
        bundle = load(os.path.join(self.dir, "model.joblib"))
        self.vec, self.gate, self.heads = bundle["vectorizer"], bundle["gate"], bundle["heads"]
        with open(os.path.join(self.dir, "labels.json"), encoding="utf-8") as f:
            self.labels = json.load(f)

    def score_batch(self, texts):
        if not texts:
            return []
        X = self.vec.transform(texts)
        gates = self.gate.predict_proba(X)[:, 1]
        cols = [
            h.predict_proba(X)[:, 1] if h is not None else [0.0] * len(texts)
            for h in self.heads
        ]
        return [(float(gates[i]), [float(c[i]) for c in cols]) for i in range(len(texts))]

    def score(self, text):
        return self.score_batch([text])[0]


class EncoderBackend:
    """Fine-tuned bert-tiny with a sigmoid head per rule, plus a gate if trained."""

    name = "encoder"
    has_gate = False  # set per instance: an older model dir ships rule heads only

    def __init__(self, model_dir=None):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self.torch = torch
        self.dir = model_dir or ENCODER_DIR
        self.tokenizer = AutoTokenizer.from_pretrained(self.dir)
        self.model = AutoModelForSequenceClassification.from_pretrained(self.dir)
        self.model.eval()
        with open(os.path.join(self.dir, "labels.json"), encoding="utf-8") as f:
            self.labels = json.load(f)
        # labels.json names the rule heads only, so one spare output column is
        # the gate; the shape is what says whether this model was trained with one
        self.has_gate = self.model.config.num_labels == len(self.labels) + 1

    def score_batch(self, texts, chunk=64):
        out = []
        n = len(self.labels)
        for i in range(0, len(texts), chunk):
            batch = texts[i : i + chunk]
            enc = self.tokenizer(
                batch, truncation=True, max_length=MAX_LEN, padding=True, return_tensors="pt"
            )
            with self.torch.no_grad():
                probs = self.torch.sigmoid(self.model(**enc).logits)
            for row in probs:
                vals = row.tolist()
                out.append((vals[n] if self.has_gate else None, vals[:n]))
        return out

    def score(self, text):
        return self.score_batch([text])[0]


def load(prefer=None, model_dir=None):
    """Return (backend, rule_desc, thresholds)."""
    linear_dir = model_dir or LINEAR_DIR
    has_linear = os.path.exists(os.path.join(linear_dir, "model.joblib"))
    if prefer == "encoder" or (prefer is None and not has_linear):
        enc = model_dir or ENCODER_DIR
        if not os.path.exists(os.path.join(enc, "config.json")):
            raise SystemExit(f"no model found in {linear_dir} or {enc}; run train_linear.py first")
        backend = EncoderBackend(enc)
    else:
        backend = LinearBackend(linear_dir)

    with open(RULES_PATH, encoding="utf-8") as f:
        rule_desc = {r["id"]: r["desc"] for r in json.load(f)["rules"]}

    thresholds = {}
    path = os.path.join(backend.dir, "thresholds.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            thresholds = json.load(f)
    return backend, rule_desc, thresholds
