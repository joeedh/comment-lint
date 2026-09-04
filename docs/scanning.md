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
- a prose comment with a Unicode codepoint above U+00FF (outside Latin-1), reported as rule
  C13 from the same kind of heuristic. C2 takes priority: a comment that is both commented-out
  code and holds a disallowed codepoint is reported once, as C2. C13 ships off by default
  (`enableRules`/`--enable-rule` turns it on) and `unicodeWhitelist` in config names codepoints
  or ranges to let through.
- a prose comment one of the deterministic checkers flags: P14 (a supporting premise
  coordinated as a peer), P13 (an alternative fenced with commas) or P15 (an interpolation
  fenced with dashes), tried in that order. Without `--split-sentences` the first that
  fires names the finding and the comment is reported once, with the offending span under
  `clauses`; the model does not also score it, so a second fault in the same comment
  surfaces on the next scan after the first is fixed. Under the flag the same choice is
  made per sentence, described below. P13 and P14 ship on by default and `disableRules`
  turns each off. P15 ships off and `enableRules`/`--enable-rule` turns it on.

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

`--split-sentences` scores each sentence of a comment on its own, so a finding's text
is one sentence rather than the whole comment. The default output still prints the
comment around it, with the flagged sentence bolded where color is on and wrapped in
`[>` and `<]` where it is off, such as on a redirected or piped stdout. A run that
brackets anything explains the brackets on one line before the first finding. A sentence
the splitter reshaped past recognition cannot be marked in place, and is named on a
`flagged sentence:` line under the comment instead. In `--json` the sentence stays under
`text` and the comment it came from is added as `comment`.

The deterministic checkers report per sentence as well. They still read the whole
comment, because `interpolation.py` decides two of its cases from where the line breaks
fall, but each span they return is reported against the sentence it landed in, and the
sentences no checker flagged are still scored by the model. A comment with two dash-fenced
sentences therefore yields two P15 findings, and a comment breaking two shapes reports
under both ids where a run without the flag reports only the first. Where one span crosses
what the sentence splitter calls a boundary, the finding covers both sentences. Such a
finding adds `sentence_start` and `sentence_end`, the sentence's offsets into `comment`.

## Config

`.commentlintrc.json`, searched from the working directory upward, nearest wins. A directory
with no `.commentlintrc.json` falls back to `.commentlintrc.jsonc` (same for the local
override, `.commentlintrc.local.json`/`.commentlintrc.local.jsonc`). The CLI overrides it.
One config per run — there are no per-file `overrides`.

```json
{
  "threshold": 0.75,
  "limit": 100,
  "exclude": ["vendor/", "**/generated/"],
  "cacheStrategy": "content"
}
```

Keys: `threshold` `limit` `minLength` `exclude` `ignorePath` `withNodeModules` `cache`
`cacheStrategy` `backend` `model` `disableRules` `enableRules` `unicodeWhitelist` `extends`.
An unknown key is an error, not a shrug. `commentlint --init` writes a `.commentlintrc.json`
with every key listed, commented out, and explained, plus an uncommented `$schema` key
pinned to the installed version, at `schema/commentlintrc.schema.json` in this repo. `load()`
strips `$schema` before the unknown-key check, so it needs no entry in `KEYS`. A hand-written
config points at the same schema for editor autocomplete by adding
`"$schema": "https://raw.githubusercontent.com/joeedh/comment-lint/v<version>/schema/commentlintrc.schema.json"`.

`extends` names a parent config to inherit from, with this config's own keys applied over
it. A plain path resolves relative to the config file's own directory, the same as `model`
and `markdownFiles`. A `//`-prefixed path resolves against the git repository root instead
(Bazel's convention for a workspace-root label), for a shared config kept elsewhere in the
tree: `"extends": "//configs/.commentlintrc.json"`.

`disableRules` is a list of rule ids (`C10`, `P9`, ...) that are never reported. The gate
that decides whether a comment is flagged still runs over every rule, so disabling one only
changes which rule a finding is named after -- a comment that would only have been named for
a disabled rule reports clean instead of shifting to a different rule.

`C10`, `C11`, `C13`, `P4`, `P10` and `P15` are in `rules.DEFAULT_DISABLED` and start off;
`enableRules` names one to turn back on. The effective disabled set is `(DEFAULT_DISABLED - enableRules) |
disableRules`, so a rule named in both stays disabled.

`unicodeWhitelist` is a list of codepoints and ranges that C13 lets through: `"U+2014"` for one
codepoint, `"U+2018-U+201F"` for an inclusive range. It only matters once C13 is enabled.

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
