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
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
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


# Everything a release ships: the package, its shipped model, and the
# launchers that run it without an interpreter named on the command line.
# Shared between the release zip and the npm vendor bundle so the file list
# is defined once.
RELEASE_FILES = [
    "commentlint",
    "predict.py",
    "data/rules.json",
    "model_linear",
    "requirements-runtime.txt",
    "bin/commentlint",
    "bin/commentlint.cmd",
]


def stage_release_files(dest: str) -> None:
    """Copy RELEASE_FILES into dest, preserving their layout."""
    os.makedirs(dest, exist_ok=True)
    for rel in RELEASE_FILES:
        src = os.path.join(ROOT, rel)
        dst = os.path.join(dest, rel)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)


def build_release_zip(zip_path: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        stage_release_files(tmp)
        os.makedirs(os.path.dirname(zip_path), exist_ok=True)
        if os.path.exists(zip_path):
            os.remove(zip_path)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for dirpath, _, filenames in os.walk(tmp):
                for name in filenames:
                    full = os.path.join(dirpath, name)
                    zf.write(full, os.path.relpath(full, tmp))


def build_npm_release(new_version: str) -> str:
    """Stage `.npm-release/`: the npm package plus a vendored source tree."""
    dest = os.path.join(ROOT, ".npm-release")
    shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(dest, exist_ok=True)

    with open(os.path.join(ROOT, "npm", "package.json"), encoding="utf-8") as f:
        pkg = json.load(f)
    pkg["version"] = new_version
    with open(os.path.join(dest, "package.json"), "w", encoding="utf-8") as f:
        json.dump(pkg, f, indent=2)
        f.write("\n")

    shutil.copytree(os.path.join(ROOT, "npm", "bin"), os.path.join(dest, "bin"))
    shutil.copytree(os.path.join(ROOT, "npm", "lib"), os.path.join(dest, "lib"))
    shutil.copy2(os.path.join(ROOT, "npm", ".npmignore"), os.path.join(dest, ".npmignore"))
    stage_release_files(os.path.join(dest, "vendor"))
    return dest


VERSION_RE = re.compile(r'^__version__\s*=\s*"([^"]+)"', re.M)


def read_version() -> str:
    init_path = os.path.join(ROOT, "commentlint", "__init__.py")
    with open(init_path, encoding="utf-8") as f:
        text = f.read()
    m = VERSION_RE.search(text)
    if not m:
        raise RuntimeError("could not find __version__ in commentlint/__init__.py")
    return m.group(1)


def write_version_init(new_version: str) -> None:
    init_path = os.path.join(ROOT, "commentlint", "__init__.py")
    with open(init_path, encoding="utf-8") as f:
        text = f.read()
    with open(init_path, "w", encoding="utf-8") as f:
        f.write(VERSION_RE.sub(f'__version__ = "{new_version}"', text, count=1))


def write_npm_package_version(new_version: str) -> None:
    pkg_path = os.path.join(ROOT, "npm", "package.json")
    with open(pkg_path, encoding="utf-8") as f:
        pkg = json.load(f)
    pkg["version"] = new_version
    with open(pkg_path, "w", encoding="utf-8") as f:
        json.dump(pkg, f, indent=2)
        f.write("\n")


def parse_version(s: str) -> tuple[int, int, int]:
    parts = s.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise ValueError(f"not a semver X.Y.Z: {s}")
    a, b, c = (int(p) for p in parts)
    return a, b, c


def compute_new_version(kind: str, current: str) -> str:
    major, minor, micro = parse_version(current)
    if kind == "major":
        return f"{major + 1}.0.0"
    if kind == "minor":
        return f"{major}.{minor + 1}.0"
    if kind == "micro":
        return f"{major}.{minor}.{micro + 1}"
    if parse_version(kind) <= (major, minor, micro):
        raise ValueError(f"{kind} is not greater than the current version {current}")
    return kind


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


@task
def test_npm(argv: Sequence[str]) -> int:
    """Exercise the npm wrapper end to end against an isolated HOME."""
    npm_cmd = "npm"
    use_shell = os.name == "nt"
    try:
        version_check = subprocess.run(
            [npm_cmd, "--version"], capture_output=True, text=True, shell=use_shell
        )
    except FileNotFoundError:
        print("test-npm: npm not found on PATH", file=sys.stderr)
        return 1
    if version_check.returncode != 0:
        print("test-npm: `npm --version` failed", file=sys.stderr)
        return 1
    major = int(version_check.stdout.strip().split(".")[0])
    if major < 7:
        got = version_check.stdout.strip()
        print(f"test-npm: npm >= 7 required (workspaces support), found {got}", file=sys.stderr)
        return 1

    # The scratch project lives near the repo rather than in the OS temp
    # directory: npm's workspaces resolution has a bug on Windows where a
    # workspace path that has to cross back through the drive root (e.g. a
    # project under C:\Users\...\AppData\Local\Temp pointing at C:\dev\...)
    # silently resolves to zero workspaces, no error, nothing installed.
    # Staying a few levels under ROOT keeps the two paths' common ancestor
    # close enough that this doesn't trigger.
    scratch_parent = os.path.join(ROOT, ".npm-test-scratch")
    os.makedirs(scratch_parent, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="run-", dir=scratch_parent)
    home = os.path.join(scratch, "home")
    project = os.path.join(scratch, "project")
    os.makedirs(home)
    os.makedirs(project)

    npm_dir = os.path.join(ROOT, "npm")
    rel_npm = os.path.relpath(npm_dir, project).replace(os.sep, "/")
    with open(os.path.join(project, "package.json"), "w", encoding="utf-8") as f:
        json.dump({"name": "commentlint-npm-test", "private": True, "workspaces": [rel_npm]}, f)

    # os.homedir() reads USERPROFILE first on Windows, HOME on POSIX; setting
    # both covers this run cross-platform without a platform check here.
    env = dict(os.environ)
    env["HOME"] = home
    env["USERPROFILE"] = home

    def run_scratch(*cmd: str) -> int:
        print(f"$ {' '.join(cmd)}   (cwd={project})", flush=True)
        return subprocess.call(list(cmd), cwd=project, env=env, shell=use_shell)

    if run_scratch(npm_cmd, "install") != 0:
        print(f"test-npm: npm install failed; scratch left at {scratch}", file=sys.stderr)
        return 1

    bin_name = "commentlint.cmd" if os.name == "nt" else "commentlint"
    bin_path = os.path.join(project, "node_modules", ".bin", bin_name)

    if run_scratch(bin_path, "--install-deps") != 0:
        print(f"test-npm: --install-deps failed; scratch left at {scratch}", file=sys.stderr)
        return 1

    fixture_path = os.path.join(project, "fixture.ts")
    with open(fixture_path, "w", encoding="utf-8") as f:
        f.write("// The leak scan is the refusal, and the refusal is what the caller reads back.\n")

    code = run_scratch(bin_path, fixture_path)
    if code not in (0, 1):
        print(f"test-npm: predict run exited {code}; scratch left at {scratch}", file=sys.stderr)
        return 1

    shutil.rmtree(scratch, ignore_errors=True)
    print("test-npm: ok")
    return 0


@task
def release(argv: Sequence[str]) -> int:
    """Bump the version, tag git, and publish source+model to a GitHub release."""
    valid_kind = bool(argv) and (
        argv[0] in ("major", "minor", "micro") or re.fullmatch(r"\d+\.\d+\.\d+", argv[0])
    )
    if not valid_kind:
        print(
            "usage: python task.py release <major|minor|micro|X.Y.Z> "
            "[--skip-check] [--skip-npm-test]",
            file=sys.stderr,
        )
        return 2
    kind = argv[0]
    flags = set(argv[1:])

    # Preflight before anything else -- a release with no way to publish it
    # isn't worth building.
    if run("gh", "auth", "status") != 0:
        print("release: not authenticated with gh; run `gh auth login` first", file=sys.stderr)
        return 1

    if "--skip-check" not in flags:
        code = TASKS["check"]([])
        if code != 0:
            return code

    # Runs after check: check is cheap and deterministic, test-npm does a
    # real npm install and a first-time venv build.
    if "--skip-npm-test" not in flags:
        code = TASKS["test-npm"]([])
        if code != 0:
            return code

    current = read_version()
    try:
        new_version = compute_new_version(kind, current)
    except ValueError as e:
        print(f"release: {e}", file=sys.stderr)
        return 2

    # Everything checkable or buildable happens before any git-mutating or
    # network-publishing step, so a failure partway through never leaves a
    # pushed tag with no matching GitHub release.
    dist_dir = os.path.join(ROOT, "dist")
    os.makedirs(dist_dir, exist_ok=True)
    zip_path = os.path.join(dist_dir, f"commentlint-v{new_version}.zip")
    build_release_zip(zip_path)
    build_npm_release(new_version)

    write_version_init(new_version)
    write_npm_package_version(new_version)

    if run("git", "add", "commentlint/__init__.py", "npm/package.json") != 0:
        return 1
    if run("git", "commit", "-m", f"Release v{new_version}") != 0:
        return 1
    if run("git", "tag", f"v{new_version}") != 0:
        return 1
    if run("git", "push", "origin", "master", "--tags") != 0:
        return 1
    if (
        run(
            "gh", "release", "create", f"v{new_version}", zip_path,
            "--title", f"v{new_version}", "--generate-notes",
        )
        != 0
    ):
        return 1

    print(f"Released v{new_version}. Next: python task.py publish-npm")
    return 0


@task
def publish_npm(argv: Sequence[str]) -> int:
    """Run `npm publish` from .npm-release/ and clean it up on success."""
    release_dir = os.path.join(ROOT, ".npm-release")
    if not os.path.isdir(release_dir):
        print(
            "publish-npm: no .npm-release/ directory; run `python task.py release <bump>` first",
            file=sys.stderr,
        )
        return 1
    print(f"$ npm publish   (cwd={release_dir})", flush=True)
    code = subprocess.call(["npm", "publish"], cwd=release_dir, shell=os.name == "nt")
    if code == 0:
        shutil.rmtree(release_dir)
        print("published; .npm-release/ removed")
    else:
        print(
            f"publish-npm: npm publish failed (exit {code}); "
            f"fix and retry `python task.py publish-npm` from {release_dir}",
            file=sys.stderr,
        )
    return code


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
