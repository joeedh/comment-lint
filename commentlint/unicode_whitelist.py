"""Parsing and membership tests for rule C13's `unicodeWhitelist`.

An entry names either one codepoint or an inclusive range, in the Unicode
standard's own U+XXXX notation, so a whitelist reads the same as the
character names it describes. A plain JSON integer is also accepted for one
codepoint, since a config assembled by a script has no reason to format it as
hex.
"""
from __future__ import annotations

import re

_SINGLE = re.compile(r"^[uU]\+([0-9A-Fa-f]{4,6})$")
_RANGE = re.compile(r"^[uU]\+([0-9A-Fa-f]{4,6})-[uU]\+([0-9A-Fa-f]{4,6})$")
MAX_CODEPOINT = 0x10FFFF

Ranges = list[tuple[int, int]]


class WhitelistError(Exception):
    """One `unicodeWhitelist` entry could not be parsed."""


def _checked(cp: int, entry: object) -> int:
    if not 0 <= cp <= MAX_CODEPOINT:
        raise WhitelistError(f"{entry!r}: {cp:#x} is outside the Unicode range (up to U+10FFFF)")
    return cp


def parse_entry(entry: object) -> tuple[int, int]:
    """One whitelist entry as an inclusive (low, high) codepoint range."""
    if isinstance(entry, int) and not isinstance(entry, bool):
        return _checked(entry, entry), _checked(entry, entry)
    if isinstance(entry, str):
        m = _RANGE.match(entry)
        if m:
            lo, hi = _checked(int(m.group(1), 16), entry), _checked(int(m.group(2), 16), entry)
            if lo > hi:
                raise WhitelistError(f"{entry!r}: range start is after its end")
            return lo, hi
        m = _SINGLE.match(entry)
        if m:
            cp = _checked(int(m.group(1), 16), entry)
            return cp, cp
    raise WhitelistError(
        f'{entry!r} is not a codepoint ("U+2014") or a range ("U+2010-U+2015")'
    )


def parse(entries: list[object]) -> Ranges:
    return [parse_entry(e) for e in entries]


def contains(ranges: Ranges, codepoint: int) -> bool:
    return any(lo <= codepoint <= hi for lo, hi in ranges)
