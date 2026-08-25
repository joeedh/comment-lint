"""Fine-tune a small local encoder as a multi-label bad-comment classifier.

Input: data/rules.json (label taxonomy) + data/labeled_all.jsonl (mined
before/after comment pairs, each carrying the rule ids its "before" text
violates) + data/clean_comments.jsonl (untouched repo comments).

Output: a local multi-label classifier (prajjwal1/bert-tiny, ~4M params,
CPU-feasible) at ./model/ that scores a comment against every rule with
enough training signal to be learnable. A coding agent calling this at
review time gets, per rule id, a violation probability -- no LLM call
needed. Thresholds are calibrated per label, not fixed at 0.5.
"""
import json
import os
import sys

import numpy as np
import torch
from datasets import Dataset
from sklearn.metrics import (
    classification_report,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    BertConfig,
    BertForSequenceClassification,
    EvalPrediction,
    Trainer,
    TrainingArguments,
)

MODEL_NAME = os.environ.get("CL_MODEL", "prajjwal1/bert-tiny")
TOKENIZER_NAME = "bert-base-uncased"  # the prajjwal1/* models share this vocab but ship no fast-tokenizer file
DATA_DIR = "data"
OUT_DIR = os.environ.get("CL_OUT", "model")
EPOCHS = int(os.environ.get("CL_EPOCHS", "40"))
LR = float(os.environ.get("CL_LR", "3e-4"))
MAX_LEN = 96
MAX_CLEAN = 2500  # downsample untouched repo comments; they are the noisiest negatives
MIN_SUPPORT = 10  # a rule below this many positives cannot be learned, so it is left out of the head
POS_WEIGHT_CAP = 20.0  # raw neg/pos reaches ~400 for the rarest rules and destabilises training
MIN_PRECISION = 0.5  # a rule that cannot flag this cleanly is switched off rather than shipped noisy
GATE_MIN_PRECISION = 0.75  # a comment wrongly called bad costs a rewrite of good prose
GATE_LABEL = "__gate__"  # the extra head column, and its key in thresholds.json
SEED = 0


def load_rules():
    with open(f"{DATA_DIR}/rules.json", encoding="utf-8") as f:
        rules = json.load(f)["rules"]
    return [r["id"] for r in rules]


def load_pairs():
    """Prefer the consensus file if data/merge_labels.py has been run."""
    path = f"{DATA_DIR}/labeled_all_v2.jsonl"
    if not os.path.exists(path):
        path = f"{DATA_DIR}/labeled_all.jsonl"
    print(f"labels from {path}", file=sys.stderr)
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def select_labels(all_rule_ids, pairs):
    """Keep only rules with enough positives to train on, in taxonomy order."""
    counts = {r: 0 for r in all_rule_ids}
    for row in pairs:
        for l in row.get("labels", []):
            if l in counts:
                counts[l] += 1
    kept = [r for r in all_rule_ids if counts[r] >= MIN_SUPPORT]
    dropped = [(r, counts[r]) for r in all_rule_ids if counts[r] < MIN_SUPPORT]
    return kept, dropped, counts


def load_examples(label_ids, pairs):
    """Assemble training rows.

    Three sources, in decreasing order of how trustworthy their labels are:
    the "before" side of a labelled pair is a positive for the rules it
    violates; the "after" side is the human-corrected version, so it is a
    gold negative that differs from its positive only in the violated
    feature; untouched repo comments are weak negatives. The "before" side
    of an *unlabelled* pair is excluded -- it was edited, so it violated
    something the heuristic labeller failed to name, and calling it clean
    teaches the model the opposite of the truth.

    Each row carries two label vectors and an eval_ok flag. Training uses the
    union of both labelers; evaluation uses only what they agreed on, and rows
    where one labeler saw a violation and the other saw none are barred from
    the held-out splits entirely. Otherwise the reported score is partly a
    measure of coin-flips between two overlapping prose rules.
    """
    label_index = {l: i for i, l in enumerate(label_ids)}
    zeros = [0.0] * len(label_ids)
    examples = []

    def vec(labels):
        v = list(zeros)
        for l in labels:
            if l in label_index:
                v[label_index[l]] = 1.0
        return v

    n_pos = n_gold_neg = n_conflict = 0
    for row in pairs:
        union = vec(row.get("labels", []))
        if sum(union) == 0:
            continue
        agreed = vec(row.get("labels_agreed", row.get("labels", [])))
        eval_ok = row.get("agreement", "full") != "conflict" and sum(agreed) > 0
        n_conflict += not eval_ok
        examples.append(
            {"text": row["before"], "labels": union, "labels_eval": agreed,
             "eval_ok": eval_ok, "kind": "before"}
        )
        examples.append(
            {"text": row["after"], "labels": list(zeros), "labels_eval": list(zeros),
             "eval_ok": True, "kind": "after"}
        )
        n_pos += 1
        n_gold_neg += 1

    with open(f"{DATA_DIR}/clean_comments.jsonl", encoding="utf-8") as f:
        clean_rows = [json.loads(line) for line in f]
    rng = np.random.default_rng(SEED)
    if len(clean_rows) > MAX_CLEAN:
        idx = rng.choice(len(clean_rows), size=MAX_CLEAN, replace=False)
        clean_rows = [clean_rows[i] for i in idx]
    for row in clean_rows:
        examples.append(
            {"text": row["comment"], "labels": list(zeros), "labels_eval": list(zeros),
             "eval_ok": True, "kind": "clean"}
        )

    print(
        f"examples: {n_pos} positives ({n_conflict} train-only, labelers split), "
        f"{n_gold_neg} corrected-version negatives, "
        f"{len(clean_rows)} untouched-comment negatives",
        file=sys.stderr,
    )
    return examples


def three_way_split(examples, seed=SEED):
    """Split so calib/test draw only from rows both labelers could agree on.

    Rows they split on still train -- they carry real signal, just not a
    scoreable label -- but they never reach a metric.
    """
    rng = np.random.default_rng(seed)
    pool = [e for e in examples if e["eval_ok"]]
    train_only = [e for e in examples if not e["eval_ok"]]
    order = rng.permutation(len(pool))
    n_held = int(0.30 * len(pool))
    held = [pool[i] for i in order[:n_held]]
    train = [pool[i] for i in order[n_held:]] + train_only

    def strip(rows, use_eval):
        return [
            {"text": r["text"], "labels": r["labels_eval" if use_eval else "labels"], "kind": r["kind"]}
            for r in rows
        ]

    half = len(held) // 2
    return (
        Dataset.from_list(strip(train, False)),
        Dataset.from_list(strip(held[:half], True)),
        Dataset.from_list(strip(held[half:], True)),
    )


def pos_weights(train_split, n_labels):
    """Per-label neg/pos ratio, capped, so rare rules are not optimised away."""
    Y = np.array(train_split["labels"])
    pos = Y.sum(axis=0)
    neg = len(Y) - pos
    w = np.where(pos > 0, neg / np.maximum(pos, 1), 1.0)
    return torch.tensor(np.minimum(w, POS_WEIGHT_CAP), dtype=torch.float)


class WeightedTrainer(Trainer):
    """Trainer with per-label positive weighting in the BCE loss.

    Without this, a rule appearing in 0.3% of rows is driven to always-negative
    because predicting zero minimises unweighted BCE.
    """

    def __init__(self, *args, pos_weight=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.pos_weight = pos_weight

    def compute_loss(self, model, inputs, return_outputs=False, **kwargs):
        labels = inputs.pop("labels")
        outputs = model(**inputs)
        loss_fn = torch.nn.BCEWithLogitsLoss(pos_weight=self.pos_weight.to(outputs.logits.device))
        loss = loss_fn(outputs.logits, labels.float())
        return (loss, outputs) if return_outputs else loss


def predict_probs(model, split, batch_size=64):
    model.eval()
    probs = []
    for i in range(0, len(split), batch_size):
        chunk = split[i : i + batch_size]
        enc = {
            "input_ids": torch.tensor(chunk["input_ids"]),
            "attention_mask": torch.tensor(chunk["attention_mask"]),
        }
        with torch.no_grad():
            probs.append(torch.sigmoid(model(**enc).logits).cpu().numpy())
    return np.vstack(probs), np.array(split["labels"])


def realistic_mask(kinds, y):
    """Drop corrected-version negatives when scoring the gate.

    The "after" text of an edited pair differs from its positive only in the
    violated feature, which makes it the ideal contrastive training negative and
    a misleading evaluation one -- nothing the gate meets in use is an
    adversarial near-duplicate of a comment someone already fixed.
    """
    return np.array([y[i] == 1 or k != "after" for i, k in enumerate(kinds)])


def calibrate_gate(probs, y, min_precision=GATE_MIN_PRECISION):
    """Loosest cut still clearing the precision floor, else the strictest available.

    The fallback deliberately isn't 0.5: that is a plausible calibration result
    here, so returning it on failure would hide the failure.
    """
    best = None
    for t in np.arange(0.05, 0.96, 0.01):
        pred = (probs > t).astype(int)
        if pred.sum() == 0:
            continue
        if precision_score(y, pred, zero_division=0) >= min_precision:
            r = recall_score(y, pred, zero_division=0)
            if best is None or r > best[0]:
                best = (r, float(t))
    if best is None:
        print(f"gate: no cut reaches precision {min_precision}; falling back to 0.95", file=sys.stderr)
        return 0.95
    return best[1]


def calibrate(probs, Y, label_ids, min_precision=MIN_PRECISION):
    """Pick each rule's threshold on a held-out split: most recall at acceptable precision.

    A single 0.5 cut silences every rule whose probabilities sit low because it
    is rare, even when its ranking is good. Maximising F1 instead overshoots the
    other way -- for a linter a false positive costs a rewritten good comment, so
    the cut is the loosest one still clearing a precision floor. A rule that
    cannot clear the floor anywhere is pinned to 1.01, i.e. off.
    """
    grid = np.arange(0.05, 0.96, 0.01)
    thresholds = {}
    for i, l in enumerate(label_ids):
        if Y[:, i].sum() == 0:
            thresholds[l] = 1.01
            continue
        ok = []
        for t in grid:
            pred = (probs[:, i] > t).astype(int)
            if pred.sum() == 0:
                continue
            p = precision_score(Y[:, i], pred, zero_division=0)
            if p >= min_precision:
                ok.append((recall_score(Y[:, i], pred, zero_division=0), float(t)))
        thresholds[l] = max(ok)[1] if ok else 1.01
    return thresholds


def main():
    all_rule_ids = load_rules()
    pairs = load_pairs()
    label_ids, dropped, counts = select_labels(all_rule_ids, pairs)
    print(
        f"{len(label_ids)}/{len(all_rule_ids)} rules have >={MIN_SUPPORT} positives; "
        f"dropped {[d[0] for d in dropped]}",
        file=sys.stderr,
    )

    examples = load_examples(label_ids, pairs)
    print(f"loaded {len(examples)} examples, {len(label_ids)} labels", file=sys.stderr)

    # three-way split: thresholds are fitted on calib so the test numbers stay honest
    ds_train, ds_calib, ds_test = three_way_split(examples)
    print(
        f"split: {len(ds_train)} train / {len(ds_calib)} calib / {len(ds_test)} test",
        file=sys.stderr,
    )

    tokenizer = AutoTokenizer.from_pretrained(TOKENIZER_NAME)

    # kept before set_format restricts the columns, and needed after it to mask
    # the corrected-version rows out of the gate's calibration
    calib_kind, test_kind = list(ds_calib["kind"]), list(ds_test["kind"])

    def tokenize(batch):
        enc = tokenizer(batch["text"], truncation=True, max_length=MAX_LEN, padding="max_length")
        # the gate rides along as one more column: same trunk, one forward pass,
        # and it learns "violates anything" jointly rather than as a second model
        enc["labels"] = [row + [float(sum(row) > 0)] for row in batch["labels"]]
        return enc

    cols = ["input_ids", "attention_mask", "labels"]
    ds_train = ds_train.map(tokenize, batched=True)
    ds_calib = ds_calib.map(tokenize, batched=True)
    ds_test = ds_test.map(tokenize, batched=True)
    for d in (ds_train, ds_calib, ds_test):
        d.set_format(type="torch", columns=cols)

    head_ids = label_ids + [GATE_LABEL]
    model_kwargs = dict(
        num_labels=len(head_ids),
        problem_type="multi_label_classification",
        id2label={i: l for i, l in enumerate(head_ids)},
        label2id={l: i for i, l in enumerate(head_ids)},
    )
    try:
        model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME, **model_kwargs)
    except ValueError:
        # older configs (e.g. prajjwal1/bert-tiny) predate the `model_type` key AutoConfig needs
        config = BertConfig.from_pretrained(MODEL_NAME, **model_kwargs)
        model = BertForSequenceClassification.from_pretrained(MODEL_NAME, config=config)

    def compute_metrics(pred: EvalPrediction):
        probs = torch.sigmoid(torch.tensor(pred.predictions)).numpy()
        preds = (probs > 0.5).astype(int)
        labels = pred.label_ids
        out = {
            "f1_micro": f1_score(labels, preds, average="micro", zero_division=0),
            "f1_macro": f1_score(labels, preds, average="macro", zero_division=0),
            "precision_micro": precision_score(labels, preds, average="micro", zero_division=0),
            "recall_micro": recall_score(labels, preds, average="micro", zero_division=0),
        }
        # macro f1 is the collapse detector: micro stays high while rare rules read zero
        out["live_labels"] = int(sum(preds[:, i].sum() > 0 for i in range(preds.shape[1])))
        return out

    args = TrainingArguments(
        output_dir=f"{OUT_DIR}/checkpoints",
        num_train_epochs=EPOCHS,
        per_device_train_batch_size=48,
        per_device_eval_batch_size=64,
        learning_rate=LR,
        eval_strategy="epoch",
        save_strategy="epoch",
        save_total_limit=1,
        logging_steps=25,
        seed=SEED,
        report_to=[],
    )

    trainer = WeightedTrainer(
        model=model,
        args=args,
        train_dataset=ds_train,
        eval_dataset=ds_calib,
        compute_metrics=compute_metrics,
        pos_weight=pos_weights(ds_train, len(label_ids)),
    )

    ckpt_dir = f"{OUT_DIR}/checkpoints"
    last_ckpt = None
    if os.path.isdir(ckpt_dir):
        ckpts = [d for d in os.listdir(ckpt_dir) if d.startswith("checkpoint-")]
        if ckpts:
            last_ckpt = os.path.join(ckpt_dir, sorted(ckpts, key=lambda d: int(d.split("-")[1]))[-1])
            print(f"resuming from {last_ckpt}", file=sys.stderr)

    trainer.train(resume_from_checkpoint=last_ckpt)

    calib_probs, calib_Y = predict_probs(model, ds_calib)
    thresholds = calibrate(calib_probs[:, : len(label_ids)], calib_Y[:, : len(label_ids)], label_ids)

    gi = len(label_ids)
    bca = calib_Y[:, gi].astype(int)
    mca = realistic_mask(calib_kind, bca)
    gate_cut = calibrate_gate(calib_probs[mca, gi], bca[mca])
    thresholds[GATE_LABEL] = gate_cut

    test_probs, test_Y = predict_probs(model, ds_test)
    thr = np.array([thresholds[l] for l in label_ids])
    test_pred = (test_probs[:, : len(label_ids)] > thr).astype(int)

    bte = test_Y[:, gi].astype(int)
    mte = realistic_mask(test_kind, bte)
    g = test_probs[mte, gi]
    gp = (g > gate_cut).astype(int)
    gate_auc = float(roc_auc_score(bte[mte], g))
    print(f"\nSTAGE 1 -- does this comment violate anything?  (cut {gate_cut:.2f})")
    print(f"  AUC {gate_auc:.3f}   base rate {bte[mte].mean():.1%}")
    print(
        f"  precision {precision_score(bte[mte], gp, zero_division=0):.2f}   "
        f"recall {recall_score(bte[mte], gp, zero_division=0):.2f}"
    )

    pos = np.where(bte == 1)[0]
    P = test_probs[:, : len(label_ids)]
    topk = {}
    print(f"\nSTAGE 2 -- which rule, given the comment is bad?  ({len(pos)} test positives)")
    for k in (1, 2, 3):
        topk[k] = sum(1 for i in pos if test_Y[i, np.argsort(-P[i])[:k]].sum() > 0) / len(pos)
        print(f"  a true rule is in the top {k}: {topk[k]:.1%}")

    print("\n=== held-out test, calibrated thresholds ===")
    print(classification_report(test_Y[:, : len(label_ids)], test_pred,
                                target_names=label_ids, zero_division=0, digits=3))

    # AUC is the threshold-free read on whether a rule carries signal at all;
    # F1 can be zero purely because the cut landed badly on a rare label.
    print(f"{'rule':5s} {'support':>7s} {'AUC':>7s} {'cut':>6s}")
    for i, l in enumerate(label_ids):
        s = int(test_Y[:, i].sum())
        auc = roc_auc_score(test_Y[:, i], test_probs[:, i]) if 0 < s < len(test_Y) else float("nan")
        print(f"{l:5s} {s:7d} {auc:7.3f} {thresholds[l]:6.2f}")

    trainer.save_model(OUT_DIR)
    tokenizer.save_pretrained(OUT_DIR)
    with open(f"{OUT_DIR}/labels.json", "w", encoding="utf-8") as f:
        json.dump(label_ids, f)
    with open(f"{OUT_DIR}/thresholds.json", "w", encoding="utf-8") as f:
        json.dump(thresholds, f, indent=2)
    with open(f"{OUT_DIR}/coverage.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "trained": label_ids,
                "untrained": {r: c for r, c in dropped},
                "gate": {"cut": gate_cut, "auc": gate_auc},
                "attribution": {f"top{k}": v for k, v in topk.items()},
            },
            f,
            indent=2,
        )


if __name__ == "__main__":
    main()
