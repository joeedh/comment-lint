"""Fine-tune a small local encoder as a multi-label bad-comment classifier.

Input: data/rules.json (label taxonomy) + data/clean_comments.jsonl (negative
examples, labels=[]) + data/labeled_chunk_*.jsonl (positive examples, each
carrying the rule ids its "before" text violates).

Output: a local multi-label classifier (default distilbert-base-uncased,
~66M params, CPU-feasible) at ./model/ that scores a comment against every
rule in the taxonomy independently. A coding agent calling this at review
time gets, per rule id, a violation probability -- no LLM call needed.
"""
import glob
import json
import sys

import numpy as np
import torch
from datasets import Dataset
from sklearn.metrics import f1_score, precision_score, recall_score
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    BertConfig,
    BertForSequenceClassification,
    EvalPrediction,
    Trainer,
    TrainingArguments,
)

MODEL_NAME = "prajjwal1/bert-tiny"
TOKENIZER_NAME = "bert-base-uncased"  # bert-tiny shares this vocab but ships no fast-tokenizer file
DATA_DIR = "data"
OUT_DIR = "model_bert_tiny"
MAX_LEN = 96
MAX_CLEAN = 2500  # downsample negatives; CPU training time is quadratic in seq len, linear in count
SEED = 0


def load_rules():
    with open(f"{DATA_DIR}/rules.json", encoding="utf-8") as f:
        rules = json.load(f)["rules"]
    return [r["id"] for r in rules]


def load_examples(label_ids):
    label_index = {l: i for i, l in enumerate(label_ids)}
    examples = []

    with open(f"{DATA_DIR}/clean_comments.jsonl", encoding="utf-8") as f:
        clean_rows = [json.loads(line) for line in f]
    rng = np.random.default_rng(SEED)
    if len(clean_rows) > MAX_CLEAN:
        idx = rng.choice(len(clean_rows), size=MAX_CLEAN, replace=False)
        clean_rows = [clean_rows[i] for i in idx]
    for row in clean_rows:
        examples.append({"text": row["comment"], "labels": [0.0] * len(label_ids)})

    for path in sorted(glob.glob(f"{DATA_DIR}/labeled_all.jsonl")):
        with open(path, encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                vec = [0.0] * len(label_ids)
                for l in row.get("labels", []):
                    if l in label_index:
                        vec[label_index[l]] = 1.0
                examples.append({"text": row["before"], "labels": vec})

    return examples


def main():
    label_ids = load_rules()
    examples = load_examples(label_ids)
    print(f"loaded {len(examples)} examples, {len(label_ids)} labels", file=sys.stderr)

    ds = Dataset.from_list(examples).train_test_split(test_size=0.15, seed=SEED)

    tokenizer = AutoTokenizer.from_pretrained(TOKENIZER_NAME)

    def tokenize(batch):
        enc = tokenizer(batch["text"], truncation=True, max_length=MAX_LEN, padding="max_length")
        enc["labels"] = batch["labels"]
        return enc

    ds = ds.map(tokenize, batched=True)
    ds.set_format(type="torch", columns=["input_ids", "attention_mask", "labels"])

    model_kwargs = dict(
        num_labels=len(label_ids),
        problem_type="multi_label_classification",
        id2label={i: l for i, l in enumerate(label_ids)},
        label2id={l: i for i, l in enumerate(label_ids)},
    )
    try:
        model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME, **model_kwargs)
    except ValueError:
        # older configs (e.g. prajjwal1/bert-tiny) predate the `model_type` key AutoConfig needs
        config = BertConfig.from_pretrained(MODEL_NAME, **model_kwargs)
        model = BertForSequenceClassification.from_pretrained(MODEL_NAME, config=config)

    def compute_metrics(pred: EvalPrediction):
        probs = torch.sigmoid(torch.tensor(pred.predictions))
        preds = (probs > 0.5).int().numpy()
        labels = pred.label_ids
        return {
            "f1_micro": f1_score(labels, preds, average="micro", zero_division=0),
            "precision_micro": precision_score(labels, preds, average="micro", zero_division=0),
            "recall_micro": recall_score(labels, preds, average="micro", zero_division=0),
        }

    args = TrainingArguments(
        output_dir=f"{OUT_DIR}/checkpoints",
        num_train_epochs=30,
        per_device_train_batch_size=48,
        per_device_eval_batch_size=64,
        learning_rate=3e-4,
        eval_strategy="epoch",
        save_strategy="epoch",
        save_total_limit=1,
        logging_steps=10,
        seed=SEED,
        report_to=[],
    )

    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=ds["train"],
        eval_dataset=ds["test"],
        compute_metrics=compute_metrics,
    )

    import os
    ckpt_dir = f"{OUT_DIR}/checkpoints"
    last_ckpt = None
    if os.path.isdir(ckpt_dir):
        ckpts = [d for d in os.listdir(ckpt_dir) if d.startswith("checkpoint-")]
        if ckpts:
            last_ckpt = os.path.join(ckpt_dir, sorted(ckpts, key=lambda d: int(d.split("-")[1]))[-1])
            print(f"resuming from {last_ckpt}", file=sys.stderr)

    trainer.train(resume_from_checkpoint=last_ckpt)
    metrics = trainer.evaluate()
    print(json.dumps(metrics, indent=2))

    trainer.save_model(OUT_DIR)
    tokenizer.save_pretrained(OUT_DIR)
    with open(f"{OUT_DIR}/labels.json", "w", encoding="utf-8") as f:
        json.dump(label_ids, f)


if __name__ == "__main__":
    main()
