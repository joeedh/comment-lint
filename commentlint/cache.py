"""Skip files whose findings are already known.

The cache stores findings rather than a clean bit, because a cached hit has to
print its results without loading the model -- which is the whole point, given
that reaching the model at all costs 2.8s.

The key hashes the model's actual bytes. Prettier's equivalent hashes plugin
names and versions, so an edited plugin silently serves stale results; hashing
6.8MB with blake2b measures at 0.01s, so there is no reason to accept that.

Two deliberate differences from prettier. The cache is on by default: prettier
writes files, where a stale entry corrupts output, while a miss here only means
a finding shows up one run later. And running without --cache does not delete
the cache file, which is surprise data loss with no upside.
"""
import hashlib
import json
import os
from typing import Any, Iterable

from . import __version__

CACHE_DIR_NODE = os.path.join("node_modules", ".cache", "commentlint")
CACHE_DIR_PLAIN = ".commentlint-cache"
CACHE_FILE = "findings.json"
MODEL_FILES = ("model.joblib", "labels.json", "thresholds.json")

Finding = dict[str, Any]
Stamp = dict[str, int | str]
Entry = dict[str, Any]  # {"stamp": Stamp, "findings": list[Finding], "comments": int}


def default_location(cwd: str | None = None) -> str:
    cwd = cwd or os.getcwd()
    base = CACHE_DIR_NODE if os.path.isdir(os.path.join(cwd, "node_modules")) else CACHE_DIR_PLAIN
    return os.path.join(cwd, base, CACHE_FILE)


def model_fingerprint(model_dir: str) -> str:
    """blake2b over the model artifacts themselves, not their names."""
    h = hashlib.blake2b(digest_size=16)
    for name in MODEL_FILES:
        path = os.path.join(model_dir, name)
        if not os.path.exists(path):
            continue
        h.update(name.encode())
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    return h.hexdigest()


def run_key(model_dir: str, options: dict[str, Any]) -> str:
    import sys

    h = hashlib.blake2b(digest_size=16)
    h.update(__version__.encode())
    h.update(f"{sys.version_info[0]}.{sys.version_info[1]}".encode())
    h.update(model_fingerprint(model_dir).encode())
    h.update(json.dumps(options, sort_keys=True, default=str).encode())
    return h.hexdigest()


def file_stamp(path: str, strategy: str = "metadata") -> Stamp:
    st = os.stat(path)
    if strategy == "content":
        h = hashlib.blake2b(digest_size=16)
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return {"size": st.st_size, "hash": h.hexdigest()}
    return {"size": st.st_size, "mtime": int(st.st_mtime_ns)}


class Cache:
    """Findings keyed by path, dropped wholesale when the run key changes."""

    def __init__(self, path: str, key: str, strategy: str = "metadata", enabled: bool = True) -> None:
        self.path = path
        self.key = key
        self.strategy = strategy
        self.enabled = enabled
        self.entries: dict[str, Entry] = {}
        self.dirty = False
        if enabled:
            self._read()

    def _read(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return
        if data.get("key") == self.key:
            self.entries = data.get("files", {})

    def get(self, path: str) -> tuple[list[Finding], int] | None:
        """Cached (findings, comment count), or None when it must be rescanned."""
        if not self.enabled:
            return None
        entry = self.entries.get(_norm(path))
        if entry is None:
            return None
        try:
            if entry.get("stamp") != file_stamp(path, self.strategy):
                return None
        except OSError:
            return None
        return entry.get("findings", []), entry.get("comments", 0)

    def put(self, path: str, findings: list[Finding], comments: int) -> None:
        if not self.enabled:
            return
        try:
            stamp = file_stamp(path, self.strategy)
        except OSError:
            return
        self.entries[_norm(path)] = {"stamp": stamp, "findings": findings, "comments": comments}
        self.dirty = True

    def save(self, seen: Iterable[str] | None = None) -> None:
        """Write the cache, dropping entries for files that are gone."""
        if not self.enabled or not self.dirty:
            return
        if seen is not None:
            keep = {_norm(p) for p in seen}
            self.entries = {k: v for k, v in self.entries.items() if k in keep}
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"key": self.key, "files": self.entries}, f)
        os.replace(tmp, self.path)


def _norm(path: str) -> str:
    return os.path.normcase(os.path.abspath(path)).replace("\\", "/")
