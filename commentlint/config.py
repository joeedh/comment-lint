""".commentlintrc.json discovery and merge.

Searched from the working directory upward, nearest wins, first hit stops --
the same rule prettier uses, minus its per-file resolution. One config per run
is enough here because every comment is scored by one model under one
threshold, and per-file config would make the single cache key impossible.
That per-file resolution is also the only reason prettier needs `overrides`,
so there is none of that either.
"""
import argparse
import json
import os
from typing import Any

CONFIG_NAME = ".commentlintrc.json"
LOCAL_CONFIG_NAME = ".commentlintrc.local.json"

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


def load(path: str) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
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
    if "model" in data:
        data["model"] = os.path.join(os.path.dirname(path), data["model"])
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
