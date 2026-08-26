"""Rule text and calibrated cuts, readable without loading a model.

Split out of backends.py so the cached path can print a finding without
pulling sklearn into the import graph.
"""
import json
import os

from . import LINEAR_DIR, RULES_PATH

GATE_KEY = "__gate__"
SCAN_KEY = "__scan__"

# Fallbacks for a model trained before its thresholds.json carried a cut. Both
# describe the linear model and neither transfers: a saturated gate puts the same
# false-alarm rate at a different score, so a shared 0.70 flagged 2.5% of one real
# tree and 9.1% of the same tree under the encoder. Prefer scan_threshold().
SCAN_THRESHOLD = 0.70
SINGLE_THRESHOLD = 0.50


def scan_threshold(model_dir: str | None = None) -> float:
    """The scan cut the model was calibrated with, read without loading it."""
    return thresholds(model_dir).get(SCAN_KEY, SCAN_THRESHOLD)


def descriptions() -> dict[str, str]:
    with open(RULES_PATH, encoding="utf-8") as f:
        return {r["id"]: r["desc"] for r in json.load(f)["rules"]}


def all_rules() -> list[dict[str, str]]:
    """Every rule in the taxonomy, trained or not: id, name and description."""
    with open(RULES_PATH, encoding="utf-8") as f:
        rules: list[dict[str, str]] = json.load(f)["rules"]
        return rules


def known_ids() -> set[str]:
    return {r["id"] for r in all_rules()}


# Style rules whose bar for what counts as a violation is a per-project call,
# not something the taxonomy can settle -- so they start off and a project
# opts back in with enableRules / --enable-rule.
DEFAULT_DISABLED: set[str] = {"C10", "C11"}


def thresholds(model_dir: str | None = None) -> dict[str, float]:
    path = os.path.join(model_dir or LINEAR_DIR, "thresholds.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data: dict[str, float] = json.load(f)
        return data
