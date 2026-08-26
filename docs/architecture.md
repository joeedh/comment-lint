# Architecture

commentlint reads source files, pulls the prose comments out of them, and scores each one
against a taxonomy of 25 comment rules held in data/rules.json. It runs locally and makes no
network calls. The output is a ranked list of suspect comments with an exit code, in the shape
a linter produces.

Scoring has two stages, and the split matters more than any other design decision here. A gate
answers whether a comment breaks some rule at all. The per-rule heads are then ranked against
each other to say which rule it most likely breaks. The second stage is a suspicion rather than
a detection: a rule that fires on 5% of comments puts mostly negatives at the top of its own
corpus-wide ranking even at a respectable AUC, while asking which of 16 rules best explains one
already-suspect comment lands a true rule in the top three 87% of the time.

## Scope: a verdict, not a rewrite

commentlint reports a violation and a rule; it never proposes replacement prose. The
caller that wrote the comment, typically an LLM inside an agent harness, holds the
surrounding code context a rewrite model would have to re-derive, and can fold a
rejection back into its own memory or instructions to avoid repeating the mistake. A
built-in rewriter would only help a caller with no LLM in the loop to act on a
rejection, such as plain CI on a human-only repository, which is a narrower case than
the one commentlint targets. A rewrite mode, if it is ever built, is a distinct opt-in
feature rather than the default output shape.

## The shape of a run

```
paths and globs
      |
      v
  discover.py     expand globs, walk with pruning, honour ignore files
      |
      v
   cache.py       a file whose stamp matches serves its stored findings and stops here
      |
      v
comments/         extract every comment, normalize it to the training text shape
      |
      v
comments/filters  drop directives, license headers and short fragments;
      |           divert commented-out code to a C2 finding without scoring it
      v
 backends.py      one batched forward pass: gate probability plus per-rule probabilities
      |
      v
   cli.py         cut on the gate, rank the rules, sort worst-first, report
```

Everything above the backend line is cheap. The backend line costs 2.8 seconds, which is why
the cache sits where it does and why the module boundaries fall where they do.

## Modules

| Module | Responsibility |
|---|---|
| `commentlint/__init__.py` | Version, and paths resolved against the package rather than the working directory |
| `commentlint/cli.py` | Argument parsing, config merge, the run modes, output formatting, exit codes |
| `commentlint/discover.py` | Glob expansion and the pruning walk that decides which files exist for this run |
| `commentlint/config.py` | `.commentlintrc.json` discovery, validation and merge |
| `commentlint/cache.py` | Findings keyed on file stamp and a run key that hashes the model bytes |
| `commentlint/backends.py` | The only module that imports scikit-learn or torch |
| `commentlint/rules.py` | Rule descriptions and calibrated cuts, readable without loading a model |
| `commentlint/feedback.py` | The false-negative ledger a user appends missed comments to |
| `commentlint/comments/tsjs.py` | Character state machine over TS/JS source |
| `commentlint/comments/pysrc.py` | `tokenize` for comments and `ast` for docstrings |
| `commentlint/comments/markdown.py` | `markdown-it-py` for prose-bearing blocks, opt-in via `--markdown`/`markdownFiles` |
| `commentlint/comments/normalize.py` | The transformation that has to match what the model was trained on |
| `commentlint/comments/filters.py` | Which comments are prose worth scoring |

`predict.py` is a shim that calls `commentlint.cli.main`. It exists because the single-comment
invocation predates the package and still works.

## Four constraints that shaped the design

### Import cost is the architecture

Measured warm, over a 0.21s bare interpreter: `import pathspec` costs 0.07s, hashing the 6.8 MB
model with blake2b costs 0.01s, and a full `joblib.load` of the model costs 2.81s. Of that
2.81s, `import sklearn` alone is 2.41s.

A fully cached run must therefore never import scikit-learn, which makes lazy backend loading a
requirement rather than a preference. Three things follow from it:

- `cli.py` imports `backends.py` inside the function that scores, never at module scope.
- The cache stores findings rather than a clean bit, so a cached hit can print its results
  without a model.
- `rules.py` exists at all. Rule descriptions and calibrated cuts are read from JSON so the
  cached path can format a finding and resolve a threshold without touching the backend.

A refactor that pulls `backends.py` into the module-level import graph would cost 2.4 seconds
per run with every ordinary test still green. tests/test_cache.py guards it by running a scan
twice in a subprocess and asserting that the second, cached run finishes with none of `sklearn`,
`torch`, `joblib` or `scipy` in `sys.modules`.

### Thresholds belong to the model, not to the tool

A cut is a property of one model's score distribution. Two gates can rank equally well and put
the same false-alarm rate at different scores, so a constant shared between them is meaningless.
The linear gate and the encoder gate spend the same budget at 0.71 and 0.99; read on one shared
0.70 they flagged 2.5% and 9.1% of the same tree, and read on their own cuts they agree at 1.4%
and 2.0%.

Every cut therefore lives in the model directory's thresholds.json. The key `__gate__` holds the
single-comment cut and `__scan__` holds the scan cut, alongside one entry per rule.

The two cuts are chosen by different criteria because they answer to different base rates. The
single-comment cut is the loosest one clearing a precision floor of 0.75 on the calibration
split. Precision moves with the base rate, and the base rate is exactly what changes between a
53%-bad evaluation set and a repository where nearly every comment is fine, so that cut flags
about 17% of a real tree. The scan cut is set by a false-alarm budget instead, which does not
move with the base rate: the score that only 3% of held-out negatives beat. Applied to the
linear model that criterion returns 0.711 on the calibration split and 0.718 on test, which
recovers the hand-picked 0.70 the constant used to carry.

A model whose thresholds.json predates the `__scan__` key falls back to 0.70. That number
describes the linear model and is correct for nothing else.

### Extraction has to match a miner that was never committed

The script that produced data/violation_pairs.jsonl is not in the tree and not in git history,
so normalize.py has to reproduce its output from evidence rather than from source. What the
11,480 training texts show: newlines survive and so does internal spacing, so nothing collapses
whitespace; opening markers are always gone; the leading `*` of a continuation line is gone with
its indentation; and no text contains a line-initial `@tag`, so tag bodies are out of
distribution and get truncated away.

Two findings from that audit are worth keeping in mind before editing the module. Backticks
appear in 5,126 of the 11,480 texts and must survive. Interior `*emphasis*` splits 774 / 10 / 8
across violation-before, violation-after and clean text, which makes it close to pure violation
signal and the strongest feature the P10 head has, so marker stripping removes only the leading
`*` of a continuation line.

tests/test_extract.py checks the whole loop rather than the pieces: it re-wraps the training
texts as comments in a synthetic source file, extracts them, normalizes them, and asserts
byte-equality with the originals.

### Ignore semantics come from pruning, not filtering

The walk prunes ignored directories during `os.scandir` instead of filtering paths afterwards.
That is a correctness fix rather than a speed one. Asked directly about `build/keep/x.ts` under
the patterns `['build/', '!build/keep/x.ts']`, pathspec reports it as not ignored while
`git check-ignore` reports it as ignored, because git does not let a negation re-include a path
whose parent directory is excluded. A walker that never descends into `build/` reproduces git
for free, and a post-filter inherits the bug.

Two smaller traps are recorded in discover.py and covered by tests. A directory-only pattern
matches only a queried path that itself ends in a slash, so every directory is tested with its
trailing slash. And an ignore layer whose relative path starts with `..` is skipped as
unrelated, so `--exclude` is anchored per scan root; anchoring it once at the working directory
made it silently exclude nothing whenever the scanned tree was somewhere else.

Nested .gitignore files are honoured, which prettier does not do. The walk already carries a
stack of specs, so the innermost layer with an opinion decides.

## Models on disk

| Directory | Contents | Tracked |
|---|---|---|
| `model_linear/` | TF-IDF word and char n-grams into a gate and 16 rule heads. This is what ships. | yes |
| `model/` | The first fine-tuned encoder, 9 labels and no gate head. Ranks rules under `--text` and refuses a scan. | yes |
| `model_gate/` | bert-tiny fine-tuned with a gate column, 16 rule heads of which 2 survived calibration | no |
| `model_mini/`, `model_v2/` | Earlier encoder runs | no |

`.gitignore` excludes `model_*/` and re-includes `model_linear/`, so a new experiment stays out
of the repository until someone decides otherwise.

Whether a model has a gate is read from its output shape rather than from a flag: labels.json
names the rule heads only, so `num_labels == len(labels) + 1` means the spare column is a gate.
That keeps older model directories loadable. Scanning cuts on the gate, so a model without one
refuses to scan rather than reporting every file clean.

The linear model wins on this data. Fitting 2.6k positives spread over 16 semantic rules is the
regime where a high-dimensional linear model beats a small transformer, and the encoder confirms
it from the other side: 14 of its 16 rule heads failed calibration and are pinned off. The
encoder's gate is the exception and is better than the linear gate, catching 29.0% of held-out
violations against 13.7% at the same false-alarm budget.

## Training

`train_linear.py` fits the shipping model in minutes. `train.py` fine-tunes the encoder in hours
and resumes from a checkpoint. Both read the same data, take the same three-way split, and share
one calibration policy, which lives in train.py and is imported by train_linear.py so the two
cannot drift.

The split is three-way on purpose. Thresholds are fitted on the calibration split so the numbers
reported on test stay honest.

Gate evaluation drops the corrected-version rows through `realistic_mask`. Those rows are ideal
contrastive negatives during training and adversarial near-duplicates during evaluation, since a
comment someone already fixed is not a thing the tool meets in the wild.

Of the 25 rules in the taxonomy, 16 have enough positives to train. Six have none at all: C1, C2,
C3, C5, C6 and C10.

## Tests

tests/ holds four files: extraction, discovery, cache and CLI. Two of them assert against
outside authorities rather than against hand-written expectations, which is what makes them
worth having. Discovery compares its answers to `git check-ignore`, and extraction compares its
normalization to the training corpus byte for byte.

`python task.py check` runs the tests and mypy together. It runs both even after one fails,
because a type error and a broken test are usually independent.

## Known gaps

- Nine rules are untrained, six of them for want of a single example. Re-mining with adjacent
  code kept would be the way to reach them.
- The scan cut's 3% budget is a judgement call, not a measurement. It reproduces the cut that
  hand inspection had already settled on, which is a reason to trust it rather than a proof.
- Rule attribution is right about 64% of the time at top-1. It is presented as a ranked
  suspicion for that reason, and any interface that shows only the top rule would be overstating
  what the model knows.
- The encoder gate is better than the linear gate but ships with unusable rule heads. Pairing
  the encoder's gate with the linear model's heads has not been tried.
