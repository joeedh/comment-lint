"""Score comments against the trained rule taxonomy. Local, no network calls.

Usage: python predict.py "comment text"        score one comment
   or: python predict.py src/ '**/*.ts'        scan files, worst findings first
   or: python predict.py --coverage            list which rules the model covers
   or: python predict.py --false-negative "…"  record a comment that wrongly passed

Verdicts come in two stages. A gate decides whether the comment violates
anything at all, then the per-rule heads are ranked against each other to say
which rule it most likely breaks. The ranking is the useful half: a rule that
fires on 5% of comments puts mostly negatives at the top of its own corpus-wide
ranking even at a respectable AUC, whereas asking which of 16 rules best
explains one suspect comment lands a true rule in the top 3 87% of the time.

So a rule listed below the gate's verdict is a ranked suspicion, not an
independent detection.

This file is a shim; the tool lives in the commentlint package.
"""
from commentlint.cli import entry

if __name__ == "__main__":
    entry()
