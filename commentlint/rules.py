"""Rule text and calibrated cuts, readable without loading a model.

Split out of backends.py so the cached path can print a finding without
pulling sklearn into the import graph.
"""
import json
import os

from . import LINEAR_DIR, RULES_PATH

# the calibrated cut is fit on a 53%-bad evaluation set; a real repo's base rate
# is far lower, so scanning uses a stricter one -- 1038 findings vs 149 over the
# same 6000 comments -- and ranks by score instead of dumping everything over it
SCAN_THRESHOLD = 0.70
SINGLE_THRESHOLD = 0.50


def descriptions() -> dict[str, str]:
    with open(RULES_PATH, encoding="utf-8") as f:
        return {r["id"]: r["desc"] for r in json.load(f)["rules"]}


def thresholds(model_dir: str | None = None) -> dict[str, float]:
    path = os.path.join(model_dir or LINEAR_DIR, "thresholds.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data: dict[str, float] = json.load(f)
        return data
