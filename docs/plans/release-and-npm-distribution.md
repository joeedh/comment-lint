# Release task + npm distribution

Status: implemented

Implementation note: `npm install` on Windows (npm 11.9) silently resolves a
`workspaces` entry to zero workspaces -- no error, nothing installed -- when
the workspace path has to cross back through the drive root to reach its
target (a project under `C:\Users\...\AppData\Local\Temp` pointing at
`C:\dev\commentlint\npm` reproduces it every time; the same target reached
from a project a few levels under `C:\dev` does not). `test-npm`'s scratch
project therefore lives under a gitignored `.npm-test-scratch/` next to
`npm/` rather than in the OS temp directory, keeping the two paths' common
ancestor close enough that the crossing never happens. The scratch `HOME`
override is unaffected by this and stays wherever `tempfile.mkdtemp()` puts
it.

## Context

commentlint has no packaging or release story today: version lives only in
`commentlint/__init__.py`, there's no `pyproject.toml`/`setup.py`, no npm
scaffolding, and no GitHub Actions. Users can only run it from a checkout via
`bin/commentlint`. The goal is a repeatable release process (`python task.py
release`) that bumps the version, tags git, and publishes a source+model zip
to a GitHub release — plus an npm package (`commentlint`) so JS-project users
can `npm install -g commentlint` and get a wrapper that manages its own
Python venv, can defer to a project-local install or a system install, and
can fetch a specific version/commit from GitHub on demand. A second task
(`publish-npm`) runs `npm publish` and cleans up the build directory on
success.

Confirmed with the user: npm package name is `commentlint` (free on the
registry — no collision with `commitlint`). Global bin script prefers a
project-local npm install (`node_modules/.bin`-style). Release zip ships
source + `model_linear/` only. GitHub release publishing uses the `gh` CLI
(already installed). Python venvs live in `~/.commentlint/pylib/<8-char
dependency hash>` so installs with identical dependencies share one venv,
including the bundled copy. The wrapper gets `--install-deps` and
`--print-dep-dir`. Config additions go in the existing `.commentlintrc.json`
(Python ignores the new `npm` key). Non-committed overrides live in
`.commentlintrc.local.json`, merged over the project config, CLI still wins.
GitHub-version fetches are transparent and cached in `~/.commentlint/installs`.

Pressure-tested against an agent review (findings folded in below): the
release pipeline now validates/builds everything it can before mutating git
or npm state, `test-npm` runs after `check` rather than before (cheap,
deterministic failures first), Windows shim detection for system-defer uses
`npm root -g` containment rather than `fs.realpath` (which can't see through
a `.cmd` shim), `pyfind.js` tries the `py` launcher on Windows the same way
`commentlint.cmd` already does, and shared-venv creation is guarded by a
lock to avoid two first-time installs racing on the same directory.

## Repo layout changes

```
npm/                          # committed npm package source
  package.json                # name, bin, files, publishConfig.access=public
  bin/commentlint.js          # the executable entry point
  lib/
    find-local.js             # walk up cwd for node_modules/commentlint, defer to it
    find-system.js            # search PATH for a non-self `commentlint`
    config.js                 # find nearest .commentlintrc.json (+ .local.json), read "npm" key
    fetch.js                  # download+cache a GitHub ref into ~/.commentlint/installs/<ref>
    venv.js                   # hash requirements-runtime.txt -> ~/.commentlint/pylib/<hash8>, ensureVenv()
    pyfind.js                 # locate a base python interpreter; platform-aware (py -3 first on win32)
  .npmignore
requirements-runtime.txt      # NEW: scikit-learn/joblib/pathspec only, split out of requirements.txt
requirements.txt              # keeps training/test/typecheck deps, adds `-r requirements-runtime.txt`
.npm-release/                 # gitignored; built by `release`, deleted by `publish-npm` on success
dist/                         # gitignored; staging dir for the release zip
```

`requirements-runtime.txt` gets an LF entry in `.gitattributes`, same as
`bin/commentlint` — the venv directory key is a hash of its exact bytes, and
without pinning, `autocrlf` normalizing it differently between a dev
checkout and the release zip would key the same dependency set to two
different `~/.commentlint/pylib/<hash8>` directories.

`requirements.txt` currently mixes runtime deps (scikit-learn, joblib,
pathspec) with training/test/typecheck-only deps (transformers, datasets,
torch, pytest, mypy). Splitting out `requirements-runtime.txt` keeps the
shipped venv from pulling in torch/transformers/pytest, and gives the
dependency-hash calculation a stable, minimal input.

## `task.py` changes

Add a shared helper (used by both the zip build and the npm vendor bundle,
so the file list is defined once):

```python
RELEASE_FILES = [
    "commentlint",           # the package directory, recursively
    "predict.py",
    "data/rules.json",       # not all of data/ -- just the taxonomy
    "model_linear",
    "requirements-runtime.txt",
    "bin/commentlint",
    "bin/commentlint.cmd",
]

def stage_release_files(dest: str) -> None: ...   # copies RELEASE_FILES into dest, preserving layout
```

New tasks, following the existing `@task` pattern (`Sequence[str] -> int`,
first docstring line is the summary shown by `usage()`):

- **`release(argv)`** — `python task.py release <major|minor|micro|X.Y.Z>`.
  The bump kind is a required positional argument — no default — so a
  release always states intent explicitly rather than silently defaulting
  to the smallest bump; `release` with no argument (or an unrecognized one)
  prints usage and exits 2, the same convention `task.py main()` already
  uses for an unknown task name. Ordered so that everything checkable or buildable
  happens before any git-mutating or network-publishing step — a failure
  partway through never leaves a pushed tag with no matching GitHub release.
  1. Preflight: `gh auth status`; abort immediately if not authenticated,
     before touching anything else.
  2. Run `check` (tests + typecheck); abort on failure unless
     `--skip-check` is passed.
  3. Run `test_npm` (see below); abort on failure unless `--skip-npm-test`
     is passed. Runs after `check` so cheap, deterministic failures surface
     first — `test_npm` is comparatively slow (a real `npm install` and a
     first-time venv build).
  4. Read `__version__` from `commentlint/__init__.py`. If `argv[0]` is
     `major`/`minor`/`micro`, bump that component of the current version
     (zeroing the components below it, standard semver-bump behavior); if
     it's an explicit `X.Y.Z`, use it verbatim after checking it's
     greater than the current version. Anything else is a usage error
     (step above).
  5. Build `dist/commentlint-vX.Y.Z.zip` from `stage_release_files()`, and
     build `.npm-release/` (copy `npm/package.json` — version not yet
     bumped in the working tree, patched into the staged copy only — plus
     `npm/bin/`, `npm/lib/`, `npm/.npmignore`, then `stage_release_files()`
     into `.npm-release/vendor/`). Both artifacts exist and are verified
     buildable before any commit/tag/push happens.
  6. Rewrite `__init__.py`'s `__version__` and `npm/package.json`'s
     `"version"` field in the working tree to the new value.
  7. `git add commentlint/__init__.py npm/package.json && git commit -m
     "Release vX.Y.Z"` (explicit paths, not `-a` — nothing else the
     working tree happens to hold gets swept into the release commit), then
     `git tag vX.Y.Z`.
  8. `git push origin master --tags`.
  9. `gh release create vX.Y.Z dist/commentlint-vX.Y.Z.zip --title vX.Y.Z
     --generate-notes`.
  10. Print next step: `python task.py publish-npm`.

- **`publish_npm(argv)`** — `python task.py publish-npm`.
  Runs `npm publish` with `cwd=.npm-release`. On exit code 0, deletes
  `.npm-release/` (`shutil.rmtree`). On failure, leaves it in place and
  prints how to retry.

- **`test_npm(argv)`** — `python task.py test-npm`. Exercises the npm
  wrapper end to end the way a real `npm install -g commentlint` user would,
  without touching the real `~/.commentlint` or global npm state. Runs
  automatically as the second step of `release` (see above, after `check`)
  and can also be run standalone.
  1. Check `npm --version` is ≥7 (workspaces support) before doing
     anything else; fail with a clear message naming the required version
     rather than letting `npm install` fail cryptically on an old global
     npm.
  2. Create a scratch directory (`tempfile.mkdtemp()`), and inside it a
     second scratch directory to act as the overridden home
     (`<scratch>/home`).
  3. Write `<scratch>/project/package.json`:
     ```json
     {
       "name": "commentlint-npm-test",
       "private": true,
       "workspaces": ["<relative path from <scratch>/project to npm/>"]
     }
     ```
     Using an npm workspace (rather than `npm install <local path>`) means
     `npm install` links the *actual* `npm/` source tree into
     `node_modules/commentlint` — no packing/copying step, no stale copy to
     go out of sync with `npm/` during development.
  4. Build an env dict that is a copy of `os.environ` with `HOME` and
     `USERPROFILE` both overridden to `<scratch>/home` (Node's
     `os.homedir()` reads `USERPROFILE` first on Windows, `HOME` on POSIX;
     setting both covers this cross-platform run without a platform check).
     Every subprocess call below uses this env and `cwd=<scratch>/project`.
  5. `run(["npm", "install"], cwd=..., env=...)` — installs the workspace,
     creating `node_modules/.bin/commentlint`.
  6. `run(["node_modules/.bin/commentlint", "--install-deps"], ...)` —
     exercises venv creation against the *repo's own* `requirements-runtime.txt`
     (found via the local `vendor/`-less dev path — see note below) into
     `<scratch>/home/.commentlint/pylib/<hash8>`.
  7. Write a small fixture file with one clearly rule-breaking comment
     (reuse an existing fixture from `tests/` if one is small and stable;
     otherwise a two-line throwaway file is fine — the point is exercising
     the pipeline, not asserting a specific rule) and
     `run(["node_modules/.bin/commentlint", fixture_path], ...)`. Accept
     exit code 0 or 1 as success (the wrapper ran predict.py to completion);
     any other code, or a spawn failure, is a task failure.
  8. On success, `shutil.rmtree(scratch, ignore_errors=True)`. On failure,
     print the scratch path and leave it for inspection.

  Note: in dev (no `.npm-release/vendor/` built yet), the wrapper's "bundled
  vendor" Python root (resolution step 5 in the wrapper's own logic below)
  needs to resolve to the *repo root* instead of a `vendor/` subdirectory
  when it's running from `npm/` directly rather than from a built package —
  detect this by checking whether `<npmPackageDir>/vendor` exists and
  falling back to `<npmPackageDir>/..` (the repo root) when it doesn't. This
  is what lets `test-npm` (and local `npm/` development generally) run
  against live source without a release build.

## Python config changes (`commentlint/config.py`)

- Add `"npm": dict` to `KEYS` — Python only type-checks it, never reads the
  nested shape (that schema belongs to the JS wrapper, not duplicated in
  Python).
- Add `.commentlintrc.local.json` support to `resolve()`: after finding the
  nearest `.commentlintrc.json` at directory `D`, also check `D/
  .commentlintrc.local.json`; if present, `load()` it (same `KEYS`
  validation) and merge its keys over the base config before CLI overrides
  are applied. `find()` itself is unchanged — the local file is only ever
  looked up next to a config that was already found, not searched
  independently.
- `tests/test_config.py` (or wherever config tests live) will need a new
  case for the local-override merge and the `npm` key — check existing
  tests during implementation and extend them rather than assuming.

## npm wrapper (`npm/bin/commentlint.js`)

Resolution order per run:

1. **Own flags first**: `--print-dep-dir` prints the resolved venv path and
   exits 0; `--install-deps` forces `ensureVenv({forceInstall: true})` on
   the resolved Python root and exits with its result. Both bypass the
   local-defer and system-defer checks below (they act on *this* install).
2. **Local-defer**: walk up from `process.cwd()` for `node_modules/
   commentlint/bin/commentlint.js`. If found and its realpath differs from
   this script's realpath, spawn it with the same argv and exit with its
   code.
3. **Config**: find the nearest `.commentlintrc.json` (+ sibling
   `.commentlintrc.local.json`), read its `npm` key
   (`{preferSystem?, fetch?: {ref}}`).
4. **System-defer** (`npm.preferSystem: true`): search `PATH` for a
   `commentlint`/`commentlint.cmd` that isn't this install. `fs.realpath`
   is not sufficient here on Windows: npm's global installer writes
   `commentlint.cmd` (and a `.ps1` shim) as real files that invoke `node
   ...\commentlint\bin\commentlint.js` by path, not as a symlink —
   `realpath` on the shim just returns the shim itself, so it can't be
   compared against this script's own realpath to detect self-reference.
   Instead, resolve `npm root -g` and treat any candidate whose path falls
   under it as "this install" (not a distinct system install) regardless
   of realpath; only a `commentlint` found outside the global npm root
   counts as a system-defer target.
5. **Resolve Python root**:
   - `npm.fetch.ref` set → `~/.commentlint/installs/<ref>/`; if absent,
     download `https://github.com/joeedh/comment-lint/archive/<ref>.zip`
     (codeload works for both tags and commit SHAs), extract, cache.
   - otherwise → `<packageDir>/vendor` if it exists (a real release
     build), else `<packageDir>/..` (the repo root — lets the wrapper run
     against live source when `npm/` is used directly, e.g. by
     `task.py test-npm` or during development, with no release build
     present).
6. **Venv**: sha256 the resolved root's `requirements-runtime.txt`,
   truncate to 8 hex chars → `~/.commentlint/pylib/<hash8>`. Create it with
   a base Python interpreter located by `pyfind.js`, platform-aware rather
   than a straight copy of `bin/commentlint`'s POSIX-only search order:
   `commentlint.cmd` already tries `py -3` before bare `python` on Windows
   because the `py` launcher, not a PATH-visible `python3`/`python`, is
   what the python.org installer puts on PATH by default — `pyfind.js`
   branches on `process.platform` and does the same (`py -3` first on
   `win32`, `python3`/`python` first elsewhere). `pip install -r
   requirements-runtime.txt` runs if not already marked complete; a marker
   file inside the venv dir avoids re-running pip on every invocation.
   First-time creation is guarded by an exclusive lock (a `mkdir`-based
   mutex directory next to the venv path, or an npm lockfile library) so
   two concurrent installs sharing the same dependency hash can't both see
   "no marker" and run `pip install` into the same directory at once.
7. **Run**: spawn `<venvDir>/{bin,Scripts}/python[.exe]
   <pyRoot>/predict.py <args>` with inherited stdio, `process.exit()` with
   its exit code unchanged (matches `bin/commentlint`'s existing forwarding
   contract).

## `.gitignore` additions

```
.npm-release/
dist/
node_modules/
.commentlintrc.local.json
```

## Verification

- `python task.py check` still passes after the `config.py` changes
  (existing + new config tests).
- `python task.py test-npm` passes standalone, confirming `npm install`
  (via workspace), `--install-deps`, and a real predict.py run all work
  against live source with an isolated `HOME`/`USERPROFILE`, and that it
  leaves the real `~/.commentlint` untouched.
- Dry-run `release` against a throwaway branch/tag (or `--skip-check
  --dry-run` if worth adding) to confirm the zip contains a runnable tree:
  extract it somewhere clean and run `python predict.py --coverage` from
  inside.
- `node npm/bin/commentlint.js --print-dep-dir` from the repo (pointed at
  `npm/` before a real release exists) to confirm hash + path logic without
  needing a built `.npm-release/`.
- After a real `release` + manual `npm install -g ./.npm-release`, run
  `commentlint` inside a throwaway project dir and confirm it creates the
  venv once, reuses it on a second run, and that `--install-deps` /
  `--print-dep-dir` behave as documented.
- Test local-defer by `npm install commentlint` inside a project (not
  global) and confirming a separately-global-installed `commentlint`
  defers to it.
