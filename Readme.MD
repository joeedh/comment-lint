# Comment Lint

This little tool uses a small machine learning model to detect AI 
slop prose in your codebase.  It was motivated by regressions in 
Anthropic's Claude Opus 5 model in 2026.

## Rules & Examples

## The commentlint command

`bin/` holds two launchers that run the linter without naming an interpreter. `commentlint`
is the sh script and `commentlint.cmd` is its counterpart for cmd and PowerShell. Put that
one directory on PATH and each shell picks up the launcher it can run.

```
export PATH="$PATH:/path/to/commentlint/bin"        # bash
$env:PATH += ';C:\path\to\commentlint\bin'          # PowerShell, this session only
```

```
commentlint src/            lint a tree
commentlint "some comment"  score one comment
commentlint --coverage      which rules the model can name
```

Report a comment the model should have flagged and did not. The text, and any note or
revision given with it, are appended to `.commentlint-feedback.json` in the working
directory; `--ledger` writes somewhere else, and `-` as the comment reads it from stdin.

```
commentlint --false-negative "// the comment that passed" \
            --note "why it should have been flagged" \
            --revision "// how it should read instead"
```

Arguments and exit codes pass straight through to predict.py, so 1 still means findings and
2 a bad argument. A `.venv` inside the checkout is used without being activated. Otherwise
the launchers take the first python they find on PATH, and exit 127 if there is none.

## Config

commentlint reads `.commentlintrc.json` the way prettier reads its config: it searches
upward from the working directory and the nearest file wins, so a subdirectory can override
a repository-wide default just by holding its own copy. A single JSON object holds every
option, with the same names the CLI flags use underneath their dashes:

```json
{
  "threshold": 0.6,
  "limit": 100,
  "minLength": 20,
  "exclude": ["vendor/**"],
  "ignorePath": [".gitignore"],
  "withNodeModules": false,
  "cache": true,
  "cacheStrategy": "content",
  "backend": "linear",
  "model": "./model_linear"
}
```

An unknown key or a value of the wrong type fails the run rather than being ignored, so a
typo in the config surfaces immediately instead of silently falling back to a default. A CLI
flag always wins over the matching config key, and `--config` points at a specific file when
the nearest one found by upward search is not the one to use. `--no-config` skips the search
entirely, scanning under CLI flags and built-in defaults alone.

## Tasks

`task.py` is the dispatch point for working on the repository itself. `python task.py` on
its own lists what is available.

```
python task.py install     dependencies, training and type-checking extras included
python task.py check       tests and types, the gate before a commit
python task.py scan src/   lint a tree
python task.py coverage    which rules the model can name, and its calibrated cuts
python task.py clean       delete tool caches
```

`check` runs every step even after one fails and exits with the worst code, so a type
error and a broken test show up in the same pass. Extra arguments reach the underlying
tool: `python task.py test -k discover` goes to pytest. Scanning follows the linter's own
exit codes, where 1 means findings and 2 means a bad argument.

See docs/scanning.md for using the linter and docs/architecture.md for how it is built.
