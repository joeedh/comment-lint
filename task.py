"""Every command this repository is run with, in one place.

    python task.py              list the tasks
    python task.py check        tests and types, the gate before a commit
    python task.py scan src/    run the linter over a tree

A Python script rather than a Makefile because the only make on this machine is
an unpacked C:\\dev\\unixtools, and every task here already needs the interpreter
anyway. Tasks run through sys.executable, so a virtualenv is picked up without
being activated first.

Exit codes are the underlying tool's, not a flattened 0/1. `scan` returning 1
means the linter found something, which a caller may want to tell apart from 2
for a bad argument.
"""
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from typing import TextIO

ROOT = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable

# What mypy is pointed at. tests/ and data/ are excluded in mypy.ini, so naming
# either here would be a silent no-op rather than the error it looks like.
TYPED = ["commentlint", "predict.py", "train.py", "train_linear.py", "task.py"]

CACHE_DIRS = frozenset({"__pycache__", ".pytest_cache", ".mypy_cache", ".commentlint-cache"})
NO_DESCEND = frozenset({".git", "node_modules"})

Task = Callable[[Sequence[str]], int]
TASKS: dict[str, Task] = {}
SUMMARY: dict[str, str] = {}


def task(fn: Task) -> Task:
    name = fn.__name__.replace("_", "-")
    TASKS[name] = fn
    SUMMARY[name] = (fn.__doc__ or "").strip().splitlines()[0]
    return fn


def run(*cmd: str) -> int:
    print(f"$ {' '.join(cmd)}", flush=True)
    return subprocess.call(list(cmd), cwd=ROOT)


@task
def test(argv: Sequence[str]) -> int:
    """Run the test suite. Extra arguments go to pytest."""
    return run(PY, "-m", "pytest", "tests/", "-q", *argv)


@task
def typecheck(argv: Sequence[str]) -> int:
    """Type-check the package and the training scripts."""
    return run(PY, "-m", "mypy", *TYPED, *argv)


@task
def check(argv: Sequence[str]) -> int:
    """Run every gate: tests, then types."""
    # Every step runs even after one fails, because a type error and a broken
    # test are usually independent and finding both in one pass is the reason
    # to have this task at all. The exit code is the worst of them.
    results: list[tuple[str, int, float]] = []
    for name in ("test", "typecheck"):
        started = time.time()
        results.append((name, TASKS[name]([]), time.time() - started))
        print()

    for name, code, elapsed in results:
        print(f"{'ok  ' if code == 0 else 'FAIL'} {name:10s} {elapsed:5.1f}s")
    return max(code for _, code, _ in results)


@task
def install(argv: Sequence[str]) -> int:
    """Install the dependencies, training and type-checking extras included."""
    return run(PY, "-m", "pip", "install", "-r", "requirements.txt", *argv)


@task
def scan(argv: Sequence[str]) -> int:
    """Lint a tree, or the repository itself when given no path."""
    return run(PY, "predict.py", *(argv or ["."]))


@task
def coverage(argv: Sequence[str]) -> int:
    """Report which rules the shipped model can name, and its calibrated cuts."""
    return run(PY, "predict.py", "--coverage", *argv)


@task
def train_linear(argv: Sequence[str]) -> int:
    """Fit the linear model into model_linear/. Minutes."""
    return run(PY, "train_linear.py", *argv)


@task
def train_encoder(argv: Sequence[str]) -> int:
    """Fine-tune the encoder into model/. Hours, and it resumes from a checkpoint."""
    return run(PY, "train.py", *argv)


@task
def clean(argv: Sequence[str]) -> int:
    """Delete tool caches. Models, logs and data are left alone."""
    removed = 0
    for dirpath, dirnames, _ in os.walk(ROOT):
        for name in list(dirnames):
            if name in NO_DESCEND:
                dirnames.remove(name)
            elif name in CACHE_DIRS:
                print(f"removing {os.path.relpath(os.path.join(dirpath, name), ROOT)}")
                shutil.rmtree(os.path.join(dirpath, name), ignore_errors=True)
                dirnames.remove(name)  # it is gone, so do not try to walk into it
                removed += 1
    print(f"{removed} cache director{'y' if removed == 1 else 'ies'} removed")
    return 0


def usage(out: TextIO = sys.stdout) -> None:
    print("usage: python task.py <task> [args...]\n", file=out)
    for name in TASKS:
        print(f"  {name:15s} {SUMMARY[name]}", file=out)


def main(argv: Sequence[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        usage()
        return 0
    name, rest = argv[0], list(argv[1:])
    fn = TASKS.get(name)
    if fn is None:
        print(f"task.py: no such task: {name}\n", file=sys.stderr)
        usage(sys.stderr)
        return 2
    return fn(rest)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
