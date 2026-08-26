"""Flag code comments that break the project's comment rules.

Paths resolve against the package rather than the working directory, because
the whole point of the tool is to run from inside some other project.
"""
import os

__version__ = "0.3.3"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES_PATH = os.path.join(ROOT, "data", "rules.json")
LINEAR_DIR = os.environ.get("CL_MODEL") or os.path.join(ROOT, "model_linear")
ENCODER_DIR = os.path.join(ROOT, "model")
