# Comment Lint

## Tasks

`task.py` is the dispatch point. `python task.py` on its own lists what is available.

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

See docs/scanning.md for the linter itself.
