# Multi-file scanning for commentlint

**Status: implemented.** What the plan got wrong, found while building it:

- **Normalization does not collapse whitespace.** The plan said it did. Measured against
  the corpus: newlines survive in 65% of texts and internal spacing survives too. Only
  the delimiters, the continuation `*`, and the outer whitespace go.
- **A run of `//` lines is one comment.** The plan never said so, and the first scan of
  visualnovel returned sentence fragments scoring 0.89 — half a comment the model had
  never seen the shape of. Runs are now merged the way `#` runs already were, which cut
  9,086 apparent comments to 7,374 real ones and 248 findings to 182.
- **Heuristic C2 findings must not share a ranking with model scores.** Giving them a
  fixed 1.0 let commented-out `vendor/` code bury every prose finding. They now get their
  own count and `--show-code`.
- **The corpus leaves a trailing `*/` on 10.9% of texts.** Label-neutral, but the char
  n-grams learned it as weak evidence of a violation: appending `*/` moves the gate score
  by +0.09 to +0.19, enough to push a clean comment across the cut. The extractor strips
  it. The model still carries the wasted feature, which argues for a cleanup retrain.
- **A bare word with no whitespace is a path, not comment text.** The planned rule scored
  a mistyped path as a one-word comment and reported it clean.

## Context

`predict.py` today scores exactly one comment, passed as a string on argv or as the whole
contents of `--file`. That is a demo harness, not a linter. To run against a real codebase it
has to take paths and globs, find the comments inside source files itself, skip what git
already ignores, and not re-score files that have not changed.

Two facts shape everything below.

**There is no comment extractor in this repo.** The miner that produced
`data/violation_pairs.jsonl` was never committed — not in the tree, not in git history. So
nothing here knows how to find a comment in a `.ts` file. That code has to be written, and it
has to reproduce the training normalization exactly or the model sees out-of-distribution text.

**The startup cost is an import, not a load.** Measured warm, over a 0.21s bare-python baseline:

| | cost over baseline |
|---|---|
| `import pathspec` | +0.07s |
| blake2b over the 6.8 MB model | +0.01s |
| `import sklearn` | **+2.41s** |
| full `joblib.load` of the model | +2.81s |

`import sklearn` is 2.41s of the 2.81s. A fully-cached run must therefore never *import*
sklearn, which makes lazy backend loading an architectural requirement rather than a style
preference. It also makes content-hashing the model into the cache key effectively free.

Decisions already taken: extract **every** comment form (doc, line, block, trailing); languages
**TS/JS + Python**; output is a prettier-style human list + exit code, plus `--json` and
`--quiet`; config file is **`.commentlintrc.json`**.

## Module layout

`predict.py` shrinks to a ~25-line delegate into a new `commentlint/` package, so the existing
single-comment invocation keeps working.

```
commentlint/
  __init__.py
  cli.py            argparse, config merge, output formatting, exit codes
  discover.py       glob expansion + pruning walker + ignore files
  config.py         .commentlintrc.json discovery and merge
  cache.py          findings cache keyed on content + model fingerprint
  backends.py       LinearBackend / EncoderBackend  <- the only sklearn importer
  comments/
    __init__.py     extract(path) -> [Comment]
    tsjs.py         character state machine
    pysrc.py        tokenize + ast
    normalize.py    the 9-step training normalization
    filters.py      skip policy, looks_like_code
```

`cli.py` must not import `backends.py` at module scope. The fully-cached path imports
`pathspec`, `json`, `hashlib` and nothing heavier.

## 1. Extractor (`commentlint/comments/`)

**`tsjs.py`** — character state machine over the raw source, ~220 lines. States: code, line
comment, block comment, single-quote, double-quote, template literal (with `${}` nesting),
regex literal. Regex-vs-division is disambiguated by the previous significant token, the
standard approach.

Bound every scanner error to one line by asserting the containment rules: a regex literal and a
quoted string never span a newline. On hitting a newline in either state, reset to code state.
A misparse then corrupts at most the line it started on, instead of desynchronising the rest of
the file.

Emit `Comment(path, line, col, kind, raw, text)` where `kind` is `doc` | `line` | `block` |
`trailing`. `trailing` is a line comment with non-whitespace before it on the same line.

**`pysrc.py`** — stdlib `tokenize` for `COMMENT` tokens plus `ast` for docstrings. No fallback
scanner: if the file does not tokenize, skip it and report it in the run summary. A hand-rolled
Python scanner would get f-strings and implicit concatenation wrong, and a wrong extraction is
worse than a skipped file.

**`normalize.py`** — must match what training saw. Verified against the 11,480 training texts:

- Strip comment markers (`//`, `/*`, `*/`, leading `*` on continuation lines, `#`).
- **Truncate at the first line-initial `@tag`.** There are **zero** line-initial `@tag` /
  `@param` / `@returns` across all 11,480 training texts, so tag bodies are entirely
  out-of-distribution — they must not reach the model.
- **Never strip backticks.** 5,126 of 11,480 texts contain them; they are in-distribution.
- **Do not strip `*emphasis*`.** Its split across the corpus is **774 violation-`before` / 10
  `after` / 8 clean** — asterisks are near-pure violation signal. Stripping them would delete
  the strongest feature the P10 head has. (Marker-stripping for block comments must therefore be
  careful to remove only the leading `*` of a continuation line, not interior asterisks.)
- Collapse internal whitespace, strip leading/trailing whitespace, normalise CR/LF.

**`filters.py`** — skip before scoring:

- Comments shorter than 40 chars (excludes 2.9% of the corpus; kills most `// TODO` noise).
- Directive comments: `eslint-disable*`, `@ts-*`, `prettier-ignore`, `# type:`, `# noqa`,
  shebangs, coding declarations.
- License/copyright headers — the first block comment in a file matching `copyright|licen[cs]e|
  SPDX|Permission is hereby granted`. Measured: a real license header scores **0.64**, a false
  positive at the calibrated 0.50 cut.
- `looks_like_code(text)` — commented-out code. Calibrate against the 5,998-row clean corpus
  with a pinned false-positive ceiling in the test suite. Do **not** feed these to the prose
  model; emit them directly as a C2 finding tagged `source: heuristic` so the provenance is
  visible in `--json`.

## 2. Discovery (`commentlint/discover.py`)

Prettier's shape, with two deliberate divergences (below). Order: expand args → walk with
pruning → filter → extract.

- Bare paths that are directories become recursive walks. Glob patterns (`**`, `*`, `?`, `[]`)
  are expanded; `**` is recursive. Use `pathspec`'s `GitIgnoreSpec` for pattern matching so
  glob semantics and ignore semantics come from one implementation.
- **Prune during `os.scandir` rather than post-filtering** — this is the first divergence from
  prettier, and it is a correctness fix, not a preference. Verified: with
  `['build/', '!build/keep/x.ts']`, `pathspec` reports `build/keep/x.ts` as *not* ignored while
  `git check-ignore` reports it as ignored by `build/`. Git does not let a negation re-include a
  path under an excluded directory. A pruning walker never descends into `build/` and so
  reproduces git for free; post-filtering inherits pathspec's bug.
- **Support nested `.gitignore`** — the second divergence. Prettier does not. Pruning makes it
  nearly free: accumulate a stack of specs as the walk descends, and test each entry against the
  stack innermost-first.
- **`pathspec` trap:** a dir-only pattern requires a trailing slash on the *queried* path.
  `spec('build/').match_file('build')` is `False`; `match_file('build/')` is `True`. Every
  directory tested during the walk must be passed with a trailing slash. This deserves its own
  test.
- Ignore-file sources, all combined with logical OR (as prettier does — a negation in one file
  cannot cross into another): `.gitignore` (nested), `.commentlintignore`, and any
  `--ignore-path`.
- Hardcoded, non-escapable: `.git`, `.hg`, `.svn`, `.jj`, `.sl`. Escapable via
  `--with-node-modules`: `node_modules`.
- `--exclude PATTERN` (repeatable) — the user's requested exclusion filters, applied as
  additional gitignore-syntax lines on top of the ignore stack.
- Extensions: `.ts .tsx .js .jsx .mjs .cjs .mts .cts` → `tsjs`; `.py .pyi` → `pysrc`. Anything
  else named explicitly on the command line is an error; anything else found by a walk is
  silently skipped.

## 3. Config (`commentlint/config.py`)

`.commentlintrc.json` searched from the CWD upward to the filesystem root, nearest wins, first
hit stops the search. `--config PATH` overrides the search; `--no-config` disables it.

**One config per run, not per file.** Prettier resolves config per file because it formats each
file under that file's options; commentlint scores every comment with one model under one
threshold. Per-file config would also make the single-`runKey` cache check impossible, and
per-file resolution is the only reason prettier needs `overrides` at all. Skip both.

Recognised keys, each mirroring a CLI flag: `threshold`, `limit`, `exclude` (array),
`withNodeModules`, `ignorePath` (array), `minLength`, `cache`, `cacheStrategy`, `backend`,
`model` (path to the model dir).

CLI beats config, matching prettier's default `--config-precedence cli-override`.

## 4. Cache (`commentlint/cache.py`)

Stored at `node_modules/.cache/commentlint/` if `node_modules` exists, else
`.commentlint-cache`, as a single JSON file.

- **Cache findings, not a clean bit.** A cached hit must be able to re-print its findings
  without loading the model, which is the entire point of the fast path.
- **Key includes a blake2b content hash of the model artifacts** (`model.joblib`,
  `labels.json`, `thresholds.json`). This closes prettier's documented blind spot — its key
  hashes plugin *names and versions*, not implementations, so an edited plugin silently serves
  stale results. Hashing costs +0.01s, measured, so there is no reason to accept that footgun.
- `runKey = blake2b(commentlint version + python major.minor + model hash + resolved options)`.
  If `runKey` differs from the stored one, drop the whole cache.
- Per file: `{mtime, size, contentHash?, findings: [...]}`.
- **Default `--cache` ON**, and default `--cache-strategy metadata` — both diverge from
  prettier. Prettier defaults cache off because a formatter writes files and a stale cache
  corrupts output; commentlint only reads, so the worst case of a stale entry is a missed
  finding on the next run. Given a 2.8s floor on the model path, on-by-default is the right
  trade. `--no-cache` disables; `--cache-strategy content` hashes file contents instead of
  trusting mtime.
- **Reject prettier's behaviour where running without `--cache` deletes the cache file.** It is
  a surprise data loss with no upside.
- Prune entries for files that no longer exist on write.

## 5. Output and exit codes (`commentlint/cli.py`)

**Scan mode ranks by score and shows the worst N.** This is the same reframe that fixed per-rule
flagging, applied at scan scale. Measured on a 6,000-comment corpus:

| gate cut | findings |
|---|---|
| 0.50 (calibrated) | 1,038 (17.3%) — untriageable |
| 0.70 | 149 (2.5%) across 98 files |
| 0.80 | 20 (0.3%) |

The calibrated 0.50 cut was fit on a 53%-bad test set; a real repo's base rate is far lower, so
it floods. But inspection shows the top-scoring "clean" comments are genuine violations that
were simply never edited (0.93 *"One undo point for the whole batch, which is the reason this is
one command and not N"* — a C7; 0.89 *"The sentence for what is about to happen — the author's
word for it, not the field's"* — a P4). So ranking quality at the top is good and 17.3%
overstates the false-positive rate. **Default scan threshold 0.70**, sorted worst-first, with
`--limit` (default 50) truncating. The single-comment path keeps the calibrated 0.50 cut, since
there the base rate argument does not apply.

Never truncate silently: print `… and N more findings below the limit` whenever anything is cut.
Same for skipped files and untokenizable Python.

Human output, prettier-style:

```
src/editor/undo.ts
  42:3  C7  0.93  One undo point for the whole batch, which is the reason...
  88:1  P4  0.81  The sentence for what is about to happen — the author's...

2 files, 4 findings (scanned 214 files, 2,611 comments in 1.4s)
```

`--json` emits `{version, files: [{path, findings: [{line, col, kind, rule, score, ranked, text,
source}]}], summary}`. `--quiet` prints only the summary line.

Exit codes: **0** clean · **1** findings · **2** usage/config error · **3** internal error.

**Positional-argument disambiguation** for back-compat: a single positional arg is treated as a
path if it exists on disk or contains a glob metacharacter, otherwise as literal comment text.
`--text` forces the literal reading, `--` forces the path reading.

## 6. Fixes carried in with this work

- **`predict.py` resolves paths relative to CWD** — `load()` opens `"data/rules.json"` and
  `LINEAR_DIR` defaults to `"model_linear"` (`predict.py:24`, `predict.py:84`). Both break the
  moment the tool runs from a target project's directory, which is now the whole point. Resolve
  against the package directory; `CL_MODEL` and `--model` still override.
- **`backends.py` needs `score_batch(texts)`** — batching is **8× faster** than per-call
  (0.093s vs 0.71s for 500 comments). At scan scale this matters more than anything else in the
  model path. Lift the existing `score()` bodies in `predict.py:44` and `predict.py:68`;
  `vec.transform` and `predict_proba` are already vectorised, so this is a shape change.
- **`requirements.txt`** is missing `joblib` — imported by both `predict.py:36` and
  `train_linear.py:31`, arriving only transitively via scikit-learn. Add it, plus `pathspec` and
  `pytest`.
- Per `CLAUDE.md`, copy this plan to `docs/plans/` as step 0.

## Verification

The repo has zero tests today, so this ships the first `tests/` directory.

**Extractor (the risky part)** — ~62 cases in `tests/test_extract.py`. Non-negotiable ones:
regex-vs-division (`a = b / c / d` vs `a = /foo/.test(x)`), a `//` inside a string, a `/*`
inside a regex character class, template-literal `${}` nesting with a comment inside the
expression, an unterminated block comment, a URL in a line comment (`http://` must not open a
comment inside a string), CRLF files, and a BOM. Each scanner-error case asserts that damage is
confined to one line.

**Normalization equivalence** — the strongest available check. Take the 11,480 training texts,
synthesise a `.ts` file whose comments are those texts re-wrapped in comment syntax, extract,
normalize, and assert byte-equality with the originals. Any mismatch is a distribution shift the
model will feel. Assert directly that no output contains a line-initial `@tag` and that
backticks and interior asterisks survive.

**Ignore semantics** — `tests/test_discover.py` builds a temp tree and asserts against
`git check-ignore` output rather than against hand-written expectations, including the nested
case and the `build/` + `!build/keep/x.ts` case that pathspec gets wrong. Assert the trailing-
slash rule explicitly.

**Cache** — round-trip; findings identical cached vs uncached; cache dropped when the model
bytes change (mutate a byte of `model.joblib` in a temp copy); `--no-cache` leaves the cache
file on disk.

**The import-graph assertion.** This is the one no ordinary test catches and the one the whole
fast path depends on: run a fully-cached scan in a subprocess with
`-X importtime`, and assert `sklearn` and `torch` are absent from the module list. A refactor
that pulls `backends.py` into `cli.py`'s import graph would otherwise silently cost 2.4s per run
with every test still green.

**End to end** — scan `C:\dev\visualnovel` (the source of the taxonomy and the training data)
and confirm: exit code 1, findings ranked worst-first, a second run is cached and under ~0.4s,
and no license header or `eslint-disable` appears in the output. Then scan this repo, whose
comments were written against these rules, and read the top 20 by hand.
