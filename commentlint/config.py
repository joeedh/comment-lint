""".commentlintrc.json discovery and merge.

Searched from the working directory upward, nearest wins, first hit stops --
the same rule prettier uses, minus its per-file resolution. One config per run
is enough here because every comment is scored by one model under one
threshold, and per-file config would make the single cache key impossible.
That per-file resolution is also the only reason prettier needs `overrides`,
so there is none of that either.

A directory holding neither `.commentlintrc.json` nor `.commentlintrc.local.json`
falls back to `.commentlintrc.jsonc`/`.commentlintrc.local.jsonc` respectively,
checked only when the `.json` name is absent so the two can never collide.

The file is JSON with `//` and `/* */` comments allowed outside string
literals, stripped before parsing.

A config can name a parent via `extends`, resolved relative to its own
directory the same way `model` and `markdownFiles` are, with the child's own
keys applied over the parent's. `extends` also accepts a `//`-prefixed path,
resolved against the git repository root the way Bazel resolves a
workspace-root label, since a path relative to the config file cannot reach a
shared config kept elsewhere in the tree.
"""
import argparse
import json
import os
import subprocess
from typing import Any

from . import rules as rules_mod
from . import unicode_whitelist
from .comments import FAMILIES

CONFIG_NAME = ".commentlintrc.json"
CONFIG_NAME_JSONC = ".commentlintrc.jsonc"
LOCAL_CONFIG_NAME = ".commentlintrc.local.json"
LOCAL_CONFIG_NAME_JSONC = ".commentlintrc.local.jsonc"
REPO_ROOT_PREFIX = "//"

KEYS: dict[str, type] = {
    "threshold": float,
    "limit": int,
    "minLength": int,
    "exclude": list,
    "ignorePath": list,
    "withNodeModules": bool,
    "cache": bool,
    "cacheStrategy": str,
    "backend": str,
    "model": str,
    "npm": dict,
    "markdown": bool,
    "markdownFiles": list,
    "disableRules": list,
    "enableRules": list,
    "unicodeWhitelist": list,
    "extends": str,
    "languageExtensions": dict,
}


class ConfigError(Exception):
    """The config file exists but cannot be used."""


def find(start: str | None = None) -> str | None:
    """Path of the nearest config at or above `start`, or None.

    `.commentlintrc.jsonc` is tried at each directory only when
    `.commentlintrc.json` isn't there, so a directory holding both never
    hides the `.json` one.
    """
    d = os.path.abspath(start or os.getcwd())
    while True:
        for name in (CONFIG_NAME, CONFIG_NAME_JSONC):
            candidate = os.path.join(d, name)
            if os.path.isfile(candidate):
                return candidate
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def _git_root(start_dir: str) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=start_dir, capture_output=True, text=True, check=False,
        )
    except OSError as e:
        raise ConfigError(f"{start_dir}: git is required to resolve a {REPO_ROOT_PREFIX} path: {e}") from e
    if result.returncode != 0:
        raise ConfigError(f"{start_dir}: not inside a git repository, so a {REPO_ROOT_PREFIX} path cannot resolve")
    return result.stdout.strip()


def _resolve_reference(path: str, reference: str) -> str:
    """A `model`/`markdownFiles`/`extends` path, resolved against `path`'s directory or the repo root."""
    if reference.startswith(REPO_ROOT_PREFIX):
        return os.path.join(_git_root(os.path.dirname(path)), reference[len(REPO_ROOT_PREFIX):].lstrip("/"))
    return os.path.join(os.path.dirname(path), reference)


def _validate_language_extensions(path: str, value: dict[str, Any]) -> None:
    """Check `languageExtensions` and lowercase its extensions in place.

    Known families, dotted extensions, each claimed by exactly one family
    across both the built-ins and this config -- lowercased here so a
    later `os.path.splitext(...)[1].lower()` lookup still finds it.
    """
    unknown = sorted(set(value) - set(FAMILIES))
    if unknown:
        raise ConfigError(
            f"{path}: languageExtensions: unknown language family/families "
            f"{', '.join(unknown)}; expected one of {', '.join(sorted(FAMILIES))}"
        )
    claimed = {ext: family for family, exts in FAMILIES.items() for ext in exts}
    for family, exts in value.items():
        if not isinstance(exts, list) or not all(isinstance(e, str) for e in exts):
            raise ConfigError(f"{path}: languageExtensions.{family} must be a list of strings")
        lowered = []
        for ext in exts:
            ext = ext.lower()
            if not ext.startswith("."):
                raise ConfigError(f"{path}: languageExtensions.{family}: {ext!r} must start with '.'")
            if ext in claimed and claimed[ext] != family:
                raise ConfigError(
                    f"{path}: languageExtensions.{family}: {ext} is already {claimed[ext]}; "
                    f"an extension can belong to only one language family"
                )
            claimed[ext] = family
            lowered.append(ext)
        value[family] = lowered


def _strip_json_comments(text: str) -> str:
    """Blank out `//` and `/* */` comments that fall outside string literals.

    Each stripped character is replaced with a space, and newlines are kept
    as newlines, so a json.JSONDecodeError raised against the result still
    points at the same line and column as the source.
    """
    out = []
    i, n = 0, len(text)
    in_string = False
    escape = False
    while i < n:
        c = text[i]
        if in_string:
            out.append(c)
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_string = False
            i += 1
            continue
        if c == '"':
            in_string = True
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                out.append(" ")
                i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            out.append("  ")
            i += 2
            while i < n and not (text[i] == "*" and i + 1 < n and text[i + 1] == "/"):
                out.append("\n" if text[i] == "\n" else " ")
                i += 1
            if i < n:
                out.append("  ")
                i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def load(path: str, _seen: frozenset[str] = frozenset()) -> dict[str, Any]:
    path = os.path.abspath(path)
    if path in _seen:
        raise ConfigError(f"{path}: extends cycle")
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
        data: dict[str, Any] = json.loads(_strip_json_comments(text))
    except (OSError, json.JSONDecodeError) as e:
        raise ConfigError(f"{path}: {e}") from e
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: expected a JSON object")

    unknown = sorted(set(data) - set(KEYS))
    if unknown:
        raise ConfigError(f"{path}: unknown option(s) {', '.join(unknown)}")
    for key, want in KEYS.items():
        if key in data and not isinstance(data[key], want):
            raise ConfigError(f"{path}: {key} must be {want.__name__}")
    if "disableRules" in data:
        unknown_rules = sorted(set(data["disableRules"]) - rules_mod.known_ids())
        if unknown_rules:
            raise ConfigError(f"{path}: unknown rule id(s) in disableRules: {', '.join(unknown_rules)}")
    if "enableRules" in data:
        unknown_rules = sorted(set(data["enableRules"]) - rules_mod.known_ids())
        if unknown_rules:
            raise ConfigError(f"{path}: unknown rule id(s) in enableRules: {', '.join(unknown_rules)}")
    if "unicodeWhitelist" in data:
        try:
            unicode_whitelist.parse(data["unicodeWhitelist"])
        except unicode_whitelist.WhitelistError as e:
            raise ConfigError(f"{path}: unicodeWhitelist: {e}") from e
    if "languageExtensions" in data:
        _validate_language_extensions(path, data["languageExtensions"])
    if "model" in data:
        data["model"] = _resolve_reference(path, data["model"])
    if "markdownFiles" in data:
        data["markdownFiles"] = [_resolve_reference(path, p) for p in data["markdownFiles"]]
    if "extends" in data:
        parent_path = _resolve_reference(path, data.pop("extends"))
        if not os.path.isfile(parent_path):
            raise ConfigError(f"{path}: extends {parent_path}: no such file")
        merged = load(parent_path, _seen | {path})
        merged.update(data)
        data = merged
    return data


def resolve(
    args: argparse.Namespace, start: str | None = None
) -> tuple[dict[str, Any], str | None]:
    """Config values under the CLI, which wins -- prettier's `cli-override`."""
    if getattr(args, "no_config", False):
        return {}, None
    path = args.config or find(start)
    if path is None:
        return {}, None
    if args.config and not os.path.isfile(path):
        raise ConfigError(f"{path}: no such file")
    data = load(path)
    config_dir = os.path.dirname(path)
    for local_name in (LOCAL_CONFIG_NAME, LOCAL_CONFIG_NAME_JSONC):
        local_path = os.path.join(config_dir, local_name)
        if os.path.isfile(local_path):
            data.update(load(local_path))
            break
    return data, path


# Every key in KEYS, commented out, with an explanation above it. A test
# checks the key set here against KEYS so the two cannot drift.
DEFAULT_CONFIG = """{
  // Gate cut: a comment scoring at or above this is reported. Omit to use
  // the model's own calibrated cut, which is what most projects should run.
  // "threshold": 0.6,

  // Most findings to print; the rest are still counted. Omit for no limit.
  // "limit": 100,

  // Skip comments shorter than this many characters.
  // "minLength": 40,

  // Extra gitignore-style patterns to skip, on top of .gitignore and
  // .commentlintignore.
  // "exclude": ["vendor/**", "**/generated/**"],

  // Extra ignore files to read, beyond .gitignore and .commentlintignore.
  // "ignorePath": [".gitignore"],

  // Scan node_modules too. Off by default.
  // "withNodeModules": false,

  // Cache findings between runs, keyed on file stamp and the model's bytes.
  // "cache": true,

  // "metadata" trusts mtime and size; "content" hashes file contents
  // instead, which is slower but survives a checkout that skips mtimes.
  // "cacheStrategy": "metadata",

  // Which backend scores comments: "linear" (what ships) or "encoder".
  // "backend": "linear",

  // Model directory to load, resolved relative to this file. A
  // "//"-prefixed path resolves from the git repository root instead.
  // "model": "./model_linear",

  // Scan .md/.markdown files during directory walks. The shipped model was
  // trained on code comments, so a markdown finding is reported as
  // experimental.
  // "markdown": false,

  // Always check these markdown files, regardless of "markdown". They are
  // added on top of the normal scan, not in place of it. Once this is
  // non-empty, "markdown" no longer opts every .md/.markdown file in the
  // tree into the walk -- only the files named here are checked.
  // "markdownFiles": ["CLAUDE.md"],

  // Rule ids never to report. The gate that decides whether a comment is
  // flagged at all still runs over every rule; disabling one only changes
  // which rule a finding is named after.
  // "disableRules": [],

  // Rule ids to turn back on even though they ship off by default (C10,
  // C11, C13 -- style calls the taxonomy can't settle for every codebase).
  // "enableRules": [],

  // Codepoints and ranges that rule C13 (no non-Latin-1 characters in a
  // comment) lets through. Each entry is either "U+XXXX" for one codepoint
  // or "U+XXXX-U+YYYY" for an inclusive range. C13 ships off by default, so
  // this only matters once it is turned on with enableRules.
  // "unicodeWhitelist": ["U+2018-U+201F"],

  // Extra file extensions for the three supported language families,
  // on top of their built-in defaults ("c-style": .ts/.tsx/.js/.jsx/.mjs/
  // .cjs/.mts/.cts, "python-style": .py/.pyi, "markdown": .md/.markdown).
  // An extension can belong to only one family. "c-style" reuses the TS/JS
  // extractor, which is a fair stand-in for other // and /* */ languages.
  // "languageExtensions": {"c-style": [".c", ".h", ".cpp", ".hpp", ".java"]},

  // Inherit from another config file; this file's own keys win over the
  // parent's. A "//"-prefixed path resolves from the git repository root,
  // the same as "model" and "markdownFiles".
  // "extends": "//configs/.commentlintrc.json",

  // Settings read by the npm wrapper, not by commentlint itself.
  // "npm": {}
}
"""


def write_default(path: str) -> None:
    """Write DEFAULT_CONFIG to `path`, refusing to overwrite an existing file."""
    if os.path.exists(path):
        raise ConfigError(f"{path}: already exists")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(DEFAULT_CONFIG)
