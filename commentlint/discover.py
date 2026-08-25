"""Turn command-line paths and globs into the list of files to scan.

Ignore handling prunes during the walk instead of filtering afterwards, which
is both faster and more correct. pathspec, asked directly, reports
`build/keep/x.ts` as not-ignored under `['build/', '!build/keep/x.ts']`; git
reports it ignored, because a negation cannot re-include a path whose parent
directory is excluded. A walker that never descends into `build/` reproduces
git for free, while a post-filter inherits the bug.

Nested .gitignore files are honoured, which prettier does not do. Pruning makes
it nearly free: the walk already carries a stack of specs, and the innermost
one that has an opinion decides -- so a `!keep.ts` in a subdirectory can
override a `*.ts` above it, as git does.

The pathspec trap worth remembering: a directory-only pattern only matches a
queried path that itself ends in a slash. `spec('build/').match_file('build')`
is False. Every directory tested here is passed with its trailing slash.
"""
import os

import pathspec

from .comments import EXTENSIONS

IGNORE_FILES = (".gitignore", ".commentlintignore")
VCS_DIRS = {".git", ".hg", ".svn", ".jj", ".sl", "__pycache__"}
GLOB_CHARS = set("*?[")


def _spec(lines):
    return pathspec.GitIgnoreSpec.from_lines(lines)


class Ignores:
    """A stack of gitignore specs, innermost first when deciding."""

    def __init__(self, layers=()):
        self.layers = list(layers)  # [(base_dir, spec)]

    def pushed(self, base, spec):
        return Ignores(self.layers + [(base, spec)])

    def ignored(self, path, is_dir):
        for base, spec in reversed(self.layers):
            rel = os.path.relpath(path, base).replace("\\", "/")
            if rel.startswith(".."):
                continue
            if is_dir:
                rel += "/"
            result = spec.check_file(rel)
            if result.include is not None:
                return result.include
        return False


def load_ignore_files(directory, names=IGNORE_FILES):
    """One spec for `directory`, or None when it holds no ignore file.

    The files are concatenated rather than layered because they sit at the same
    level; a negation in one can legitimately answer a pattern in the other.
    """
    lines = []
    for name in names:
        path = os.path.join(directory, name)
        if os.path.isfile(path):
            with open(path, encoding="utf-8", errors="replace") as f:
                lines.extend(f.read().splitlines())
    return _spec(lines) if lines else None


def walk(root, ignores, with_node_modules=False, pattern=None, on_skip=None):
    """Yield scannable files under `root`, pruning ignored directories."""
    spec = load_ignore_files(root)
    if spec is not None:
        ignores = ignores.pushed(root, spec)

    try:
        entries = sorted(os.scandir(root), key=lambda e: e.name)
    except OSError as e:
        if on_skip:
            on_skip(root, str(e))
        return

    for entry in entries:
        name = entry.name
        try:
            is_dir = entry.is_dir(follow_symlinks=False)
        except OSError:
            continue

        if is_dir:
            if name in VCS_DIRS:
                continue
            if name == "node_modules" and not with_node_modules:
                continue
            if ignores.ignored(entry.path, True):
                continue
            yield from walk(entry.path, ignores, with_node_modules, pattern, on_skip)
            continue

        if os.path.splitext(name)[1].lower() not in EXTENSIONS:
            continue
        if ignores.ignored(entry.path, False):
            continue
        if pattern is not None and not _matches(pattern, entry.path):
            continue
        yield entry.path


def _matches(pattern_spec, path):
    base, spec = pattern_spec
    rel = os.path.relpath(path, base).replace("\\", "/")
    return spec.match_file(rel)


def split_glob(arg):
    """Split a glob into its fixed base directory and the pattern beneath it."""
    parts = arg.replace("\\", "/").split("/")
    fixed = []
    for i, part in enumerate(parts):
        if GLOB_CHARS & set(part):
            return "/".join(fixed) or ".", "/".join(parts[i:])
        fixed.append(part)
    return arg, None


def discover(paths, exclude=(), ignore_path=(), with_node_modules=False, on_skip=None):
    """Every file to scan, de-duplicated and in stable order."""
    base_layers = []
    for p in ignore_path:
        if os.path.isfile(p):
            with open(p, encoding="utf-8", errors="replace") as f:
                base_layers.append((os.path.dirname(os.path.abspath(p)) or ".", _spec(f.read().splitlines())))
    ignores = Ignores(base_layers)
    # anchored per scan root rather than once at the cwd: a relative path that
    # climbs out of its base is skipped as unrelated, so a cwd-anchored
    # `--exclude vendor/` silently excludes nothing when the root is elsewhere
    exclude_spec = _spec(exclude) if exclude else None

    out, seen = [], set()

    def add(path):
        key = os.path.normcase(os.path.abspath(path))
        if key not in seen:
            seen.add(key)
            out.append(path)

    def rooted(root):
        if exclude_spec is None:
            return ignores
        return ignores.pushed(os.path.abspath(root), exclude_spec)

    for arg in paths or ["."]:
        base, pattern = split_glob(arg)
        if pattern is None:
            if os.path.isfile(arg):
                add(arg)  # named outright, so the user has already decided
                continue
            if not os.path.isdir(arg):
                raise FileNotFoundError(arg)
            for f in walk(arg, rooted(arg), with_node_modules, None, on_skip):
                add(f)
            continue
        if not os.path.isdir(base):
            continue
        pat = (os.path.abspath(base), _spec([pattern]))
        for f in walk(base, rooted(base), with_node_modules, pat, on_skip):
            add(f)

    return out
