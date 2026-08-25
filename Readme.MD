# Comment Lint

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

Arguments and exit codes pass straight through to predict.py, so 1 still means findings and
2 a bad argument. A `.venv` inside the checkout is used without being activated. Otherwise
the launchers take the first python they find on PATH, and exit 127 if there is none.

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
