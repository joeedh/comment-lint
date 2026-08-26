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

Report a comment the model should have flagged and did not, or one it flagged but
shouldn't have. The text, and any note, revision or rule given with it, are appended to
`.commentlint-feedback.json` in the working directory; `--ledger` writes somewhere else, and
`-` as the comment reads it from stdin.

```
commentlint --false-negative "// the comment that passed" \
            --note "why it should have been flagged" \
            --revision "// how it should read instead"

commentlint --false-positive "// the comment that was wrongly flagged" \
            --rule P1 \
            --note "why the verdict was wrong"
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
  "model": "./model_linear",
  "markdown": false,
  "markdownFiles": ["CLAUDE.md"],
  "disableRules": ["C10", "P9"]
}
```

An unknown key or a value of the wrong type fails the run rather than being ignored, so a
typo in the config surfaces immediately instead of silently falling back to a default. A CLI
flag always wins over the matching config key, and `--config` points at a specific file when
the nearest one found by upward search is not the one to use. `--no-config` skips the search
entirely, scanning under CLI flags and built-in defaults alone.

`disableRules` (or `--disable-rule RULE`, repeatable) is a list of rule ids -- `C10`, `P9`,
and so on -- that never get reported. An unknown id fails the run the same way an unknown
config key does. Disabling a rule only changes which rule a finding is named after: the gate
that decides whether a comment is flagged at all is a single score across every rule and is
not affected, so a comment that would only have been named for a disabled rule is now
reported clean rather than under a different rule. `C2` (commented-out code) is a heuristic
outside the model and can be disabled the same way.

### Markdown

commentlint does not scan `.md`/`.markdown` files by default. `--markdown` (or `"markdown":
true` in config) opts a directory walk into them; `--markdown-file PATH` (or
`"markdownFiles"`, repeatable/list) always checks specific files regardless of the walk, and
when that list is non-empty it takes over from the walk-wide flag -- only the named files get
checked, not the whole tree. A file named directly on the command line is always scanned, with
or without either setting. `--markdown` combined with `--with-node-modules` also reaches every
vendored `README.md` under `node_modules`.

The shipped model was trained on code comments, not on prose against a style guide, so a
markdown finding is a weaker signal than a code-comment one. It is tagged `"model-markdown"`
and carries `"experimental": true` in `--json`, and a banner calls it out in the human report.

`<!-- commentlint-off -->` and `<!-- commentlint-on -->`, each on its own line, disable
scanning between them. A block whose lines touch either marker is dropped entirely, and an
unterminated `commentlint-off` disables the rest of the file. An HTML comment is the marker
because it stays literal in every CommonMark context -- a fenced block, a table cell, a
blockquote -- where a plain-text directive would either be swallowed as prose or need its own
escaping rules.

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
