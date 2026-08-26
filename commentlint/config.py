""".commentlintrc.json discovery and merge.

Searched from the working directory upward, nearest wins, first hit stops --
the same rule prettier uses, minus its per-file resolution. One config per run
is enough here because every comment is scored by one model under one
threshold, and per-file config would make the single cache key impossible.
That per-file resolution is also the only reason prettier needs `overrides`,
so there is none of that either.

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

CONFIG_NAME = ".commentlintrc.json"
LOCAL_CONFIG_NAME = ".commentlintrc.local.json"
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
    "extends": str,
}


class ConfigError(Exception):
    """The config file exists but cannot be used."""


def find(start: str | None = None) -> str | None:
    """Path of the nearest config at or above `start`, or None."""
    d = os.path.abspath(start or os.getcwd())
    while True:
        candidate = os.path.join(d, CONFIG_NAME)
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


def load(path: str, _seen: frozenset[str] = frozenset()) -> dict[str, Any]:
    path = os.path.abspath(path)
    if path in _seen:
        raise ConfigError(f"{path}: extends cycle")
    try:
        with open(path, encoding="utf-8") as f:
            data: dict[str, Any] = json.load(f)
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
    local_path = os.path.join(os.path.dirname(path), LOCAL_CONFIG_NAME)
    if os.path.isfile(local_path):
        data.update(load(local_path))
    return data, path
