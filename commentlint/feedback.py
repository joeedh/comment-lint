"""Record comments the model should have flagged but did not.

The ledger is a plain JSON array on disk, appended to one entry at a time, so
it can be read by anything and hand-edited when an entry is wrong. Nothing in
here imports the model: reporting a miss is a bookkeeping step and must not pay
sklearn's 2.4s import.

The write is read-modify-write through a temporary file and os.replace, which
keeps a crashed run from truncating entries recorded earlier.
"""
import json
import os
from datetime import datetime, timezone
from typing import Any

from . import __version__

LEDGER_NAME = ".commentlint-feedback.json"
FALSE_NEGATIVE = "false_negative"

Entry = dict[str, Any]


class LedgerError(Exception):
    """The ledger exists but cannot be read or written."""


def default_location(cwd: str | None = None) -> str:
    return os.path.join(cwd or os.getcwd(), LEDGER_NAME)


def load(path: str) -> list[Entry]:
    """Entries already in the ledger. A missing or empty file has none."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        raise LedgerError(f"{path}: {e}") from e
    if not text.strip():
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise LedgerError(f"{path}: {e}") from e
    if not isinstance(data, list):
        raise LedgerError(f"{path}: expected a JSON array of entries")
    return data


def entry(text: str, note: str | None = None, revision: str | None = None,
          now: datetime | None = None) -> Entry:
    """One false-negative report. Absent optional fields are left out."""
    record: Entry = {
        "kind": FALSE_NEGATIVE,
        "recorded": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
        "version": __version__,
        "text": text,
    }
    if note:
        record["note"] = note
    if revision:
        record["revision"] = revision
    return record


def append(path: str, record: Entry) -> int:
    """Add one entry to the ledger and return how many it then holds."""
    entries = load(path)
    entries.append(record)
    parent = os.path.dirname(os.path.abspath(path))
    try:
        os.makedirs(parent, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=1, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    except OSError as e:
        raise LedgerError(f"{path}: {e}") from e
    return len(entries)
