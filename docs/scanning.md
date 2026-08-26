# Scanning files

```
python predict.py .                      # scan the tree, worst findings first
python predict.py src/ 'packages/**/*.ts'
python predict.py "a comment to score"   # single comment, as before
```

Exit codes: `0` nothing found, `1` findings, `2` bad usage or config, `3` internal error.

## What gets scanned

`.ts .tsx .js .jsx .mjs .cjs .mts .cts` and `.py .pyi`.

A directory is walked recursively. Globs support `*`, `?`, `[]` and `**`, and are matched
with gitignore semantics, so `*.ts` matches at any depth.

Skipped: anything `.gitignore` or `.commentlintignore` excludes (including nested ones),
`node_modules` (unless `--with-node-modules`), and `.git .hg .svn .jj .sl __pycache__`.
Add more with `--exclude PATTERN` (repeatable, gitignore syntax) or `--ignore-path FILE`.

Ignore rules are applied by pruning the walk, which matches git exactly — including the
case where a negation cannot re-include a file under an excluded directory. A file named
outright on the command line is scanned regardless, since naming it is the decision.

## What gets scored

Every comment form: `/** doc */`, `/* block */`, `// line`, trailing `// after code`, `#`
comments and Python docstrings. A run of consecutive `//` (or `#`) lines is one comment,
because that is what its author wrote and what the model was trained on.

Not scored:

- comments under 40 characters (`--min-length`)
- directives — `eslint-disable`, `@ts-ignore`, `prettier-ignore`, `# noqa`, shebangs
- license and copyright headers
- commented-out code, which is reported as rule C2 from a heuristic rather than sent to
  the prose model. It is counted in the summary and listed by `--show-code`.

## Reading the output

```
packages/authoring/src/loop.ts
   398:1   ruleP4   0.85  Both shapes are accepted: one question is the common case...

653 files, 7374 comments, 182 findings (cut 0.71, 0 cached, 7.3s)
```

Findings are ranked worst-first and cut off at `--limit` (default: no limit); whatever is
hidden is always counted on the line that hides it.

The score is the gate: how likely the comment breaks *some* rule. The rule beside it is
the best of 16 ranked suspects, right about 64% of the time and in the top three 87% of
the time — a suspicion to check, not a detection. `--top N` names more of them.

Scanning uses a stricter cut than the single-comment path, and reads it from the model's
own `thresholds.json` under the key `__scan__`. The single-comment cut is calibrated for
precision on a 53%-bad evaluation set; a real repository's rate is far lower, so that cut
flags about 17% of every comment in a tree. Precision moves with the base rate and the
base rate is what changed, so the scan cut is set by a false-alarm budget instead: the
score that only 3% of held-out clean comments beat. Lower it with `--threshold` to dig.

The cut belongs to the model rather than to the tool because two gates can rank equally
well and still put that score in different places. The linear gate spends its 3% at 0.71
and the encoder gate at 0.99. Read on one shared constant of 0.70 they look wildly
different — 2.5% of one tree against 9.1% of the same tree — and read on their own cuts
they agree, at 1.4% and 2.0%. A model whose `thresholds.json` predates the key falls back
to 0.70, which is the linear model's number and correct for nothing else.

`--json` gives every finding with its position, ranked rules, text and `source`
(`model` or `heuristic`). `--quiet` prints the summary alone.

## Config

`.commentlintrc.json`, searched from the working directory upward, nearest wins. The CLI
overrides it. One config per run — there are no per-file `overrides`.

```json
{
  "threshold": 0.75,
  "limit": 100,
  "exclude": ["vendor/", "**/generated/"],
  "cacheStrategy": "content"
}
```

Keys: `threshold` `limit` `minLength` `exclude` `ignorePath` `withNodeModules` `cache`
`cacheStrategy` `backend` `model`. An unknown key is an error, not a shrug.

`backend` is `linear` or `encoder`. Scanning cuts on the gate, so a model without a gate
head refuses a scan rather than reporting every file clean; it still ranks rules for one
comment under `--text`. The encoder in `model/` has no gate and behaves that way. Whether
a model has one is read from its output shape, not from a flag: `labels.json` names the
rule heads only, so one spare output column is the gate.

## Cache

On by default, in `node_modules/.cache/commentlint/` or `.commentlint-cache/`. A full
rescan of 653 files takes 8s; cached it takes 0.3s, because a cached run never imports
scikit-learn — that import alone is 2.4s.

The key includes a hash of the model's actual bytes, so retraining invalidates the cache
on its own. `--cache-strategy content` hashes file contents instead of trusting mtime.
`--no-cache` skips the cache and, unlike prettier, leaves the existing one alone.
