"""Fit a linear bad-comment classifier over character and word n-grams.

Same inputs, splits and calibration policy as train.py -- only the model
differs. On this dataset it beats the fine-tuned encoder on 13 of 16 rules,
because 2.6k positives spread over 16 semantic rules is the regime where a
high-dimensional linear model wins and a transformer overfits to whichever two
labels dominate the loss.

Word n-grams alone miss P4 and P10, whose evidence is punctuation the default
tokenizer discards: markup asterisks, a trailing colon. char_wb n-grams see
those, so the two feature spaces are unioned rather than chosen between.

The model has two stages, because per-rule detection across a whole corpus and
rule attribution for one suspect comment are different problems and only the
second one works well here. A rule can reach AUC 0.82 and still put almost
nothing but negatives at the top of its ranking, since it fires on 5% of
comments; asking "which rule does THIS comment break" avoids that base rate
entirely.

  gate   one head: does this comment violate anything at all?
  heads  one head per rule, ranked against each other for attribution

Output: model_linear/ holding the vectoriser, the gate, the per-rule heads, and
the labels/thresholds/coverage files predict.py reads.
"""
import json
import os
import sys

import numpy as np
from joblib import dump
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_score, recall_score, roc_auc_score
from sklearn.pipeline import FeatureUnion

import train as T

OUT_DIR = os.environ.get("CL_OUT", "model_linear")
C = float(os.environ.get("CL_C", "1.0"))
# the gate's masking and cut policy live in train.py so both models share one
realistic_mask, calibrate_gate = T.realistic_mask, T.calibrate_gate


def build_vectorizer():
    return FeatureUnion(
        [
            ("word", TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True)),
            ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=3, sublinear_tf=True)),
        ]
    )


def fit_heads(X, Y, label_ids):
    """One balanced one-vs-rest head per rule; a rule with no positives gets None."""
    heads = []
    for i, r in enumerate(label_ids):
        if Y[:, i].sum() < 2:
            print(f"  {r}: too few train positives, head skipped", file=sys.stderr)
            heads.append(None)
            continue
        heads.append(LogisticRegression(max_iter=3000, C=C, class_weight="balanced").fit(X, Y[:, i]))
    return heads


def probs_for(heads, X):
    out = np.zeros((X.shape[0], len(heads)))
    for i, h in enumerate(heads):
        if h is not None:
            out[:, i] = h.predict_proba(X)[:, 1]
    return out


def main():
    all_rule_ids = T.load_rules()
    pairs = T.load_pairs()
    label_ids, dropped, _ = T.select_labels(all_rule_ids, pairs)
    print(
        f"{len(label_ids)}/{len(all_rule_ids)} rules have >={T.MIN_SUPPORT} positives; "
        f"dropped {[d[0] for d in dropped]}",
        file=sys.stderr,
    )

    ds_train, ds_calib, ds_test = T.three_way_split(T.load_examples(label_ids, pairs))
    print(f"split: {len(ds_train)} train / {len(ds_calib)} calib / {len(ds_test)} test", file=sys.stderr)

    vec = build_vectorizer()
    Xtr = vec.fit_transform(ds_train["text"])
    Xca, Xte = vec.transform(ds_calib["text"]), vec.transform(ds_test["text"])
    Ytr, Yca, Yte = (np.array(d["labels"]) for d in (ds_train, ds_calib, ds_test))
    btr, bca, bte = [(Y.sum(1) > 0).astype(int) for Y in (Ytr, Yca, Yte)]
    print(f"features: {Xtr.shape[1]}", file=sys.stderr)

    gate = LogisticRegression(max_iter=3000, C=C, class_weight="balanced").fit(Xtr, btr)
    mca, mte = realistic_mask(ds_calib["kind"], bca), realistic_mask(ds_test["kind"], bte)
    gate_cut = calibrate_gate(gate.predict_proba(Xca)[:, 1][mca], bca[mca])

    g = gate.predict_proba(Xte)[:, 1][mte]
    gp = (g > gate_cut).astype(int)
    print(f"\nSTAGE 1 -- does this comment violate anything?  (cut {gate_cut:.2f})")
    print(f"  AUC {roc_auc_score(bte[mte], g):.3f}   base rate {bte[mte].mean():.1%}")
    print(
        f"  precision {precision_score(bte[mte], gp, zero_division=0):.2f}   "
        f"recall {recall_score(bte[mte], gp, zero_division=0):.2f}"
    )

    heads = fit_heads(Xtr, Ytr, label_ids)
    P = probs_for(heads, Xte)
    pos = np.where(bte == 1)[0]
    print(f"\nSTAGE 2 -- which rule, given the comment is bad?  ({len(pos)} test positives)")
    topk = {}
    for k in (1, 2, 3):
        topk[k] = sum(1 for i in pos if Yte[i, np.argsort(-P[i])[:k]].sum() > 0) / len(pos)
        print(f"  a true rule is in the top {k}: {topk[k]:.1%}")
    print(f"  (random top-1 baseline: {Yte[pos].sum() / (len(pos) * len(label_ids)):.1%})")

    print(f"\n{'rule':5s} {'support':>7s} {'AUC':>7s}")
    for i, r in enumerate(label_ids):
        n = int(Yte[:, i].sum())
        auc = roc_auc_score(Yte[:, i], P[:, i]) if 0 < n < len(Yte) else float("nan")
        print(f"{r:5s} {n:7d} {auc:7.3f}")

    os.makedirs(OUT_DIR, exist_ok=True)
    dump({"vectorizer": vec, "gate": gate, "heads": heads}, f"{OUT_DIR}/model.joblib", compress=3)
    with open(f"{OUT_DIR}/labels.json", "w", encoding="utf-8") as f:
        json.dump(label_ids, f)
    with open(f"{OUT_DIR}/thresholds.json", "w", encoding="utf-8") as f:
        json.dump({"__gate__": gate_cut}, f, indent=1)
    with open(f"{OUT_DIR}/coverage.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "trained": label_ids,
                "untrained": {r: n for r, n in dropped},
                "gate": {"cut": gate_cut, "auc": float(roc_auc_score(bte[mte], g))},
                "attribution": {f"top{k}": v for k, v in topk.items()},
            },
            f,
            indent=1,
        )
    print(f"\nsaved to {OUT_DIR}/", file=sys.stderr)


if __name__ == "__main__":
    main()
