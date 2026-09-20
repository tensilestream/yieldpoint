"""What the ledger already knows about a file, for the pre-edit brief.

A rule that has fired on this path before is the cheapest prediction available:
nobody has to guess what might go wrong here, because it already did. The
ledger stores ``file::rule`` per finding, so this is a fold over recorded
facts — no source is parsed, no model is called, and no clock is read.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class History:
    """Everything the ledger holds about one path."""

    repeats: tuple[tuple[str, int], ...] = ()
    """Rules that have fired here before, commonest first."""

    last_checked: int = 0
    """When this path was last analysed. Zero means nothing ever has, which is
    a different statement from "it was analysed and was clean"."""

    @property
    def seen(self) -> bool:
        return bool(self.last_checked)


def _split(key: str) -> tuple[str, str]:
    """Split a ``file::rule`` ledger key into its two halves."""
    file, _, rule = key.partition("::")
    return file, rule


def _ranked(counts: Counter) -> tuple[tuple[str, int], ...]:
    """Commonest first, then alphabetical so the order is stable."""
    return tuple(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def fold(events) -> dict[str, History]:
    """One pass over the ledger, keyed by path.

    Runs on every brief, so it stays a single pass. A path that was checked but
    never produced a finding still appears, because "checked and clean" is
    worth saying and is not the same as "never looked at".
    """
    repeats: dict[str, Counter] = {}
    checked: dict[str, int] = {}
    for event in events:
        for key in event.keys:
            file, rule = _split(key)
            if rule:
                repeats.setdefault(file, Counter())[rule] += 1
        for path in event.checked:
            checked[path] = max(checked.get(path, 0), event.at)
    return {
        path: History(repeats=_ranked(repeats.get(path, Counter())),
                      last_checked=checked.get(path, 0))
        for path in set(repeats) | set(checked)
    }


def stale(record: History, source: Path) -> bool:
    """True when the file changed after the last time anything analysed it.

    Compares two stored facts — the ledger's timestamp and the file's mtime —
    rather than reading a clock, so the answer does not depend on when it is
    asked (RULES.md section 4).
    """
    if not record.seen:
        return False
    try:
        return source.stat().st_mtime > record.last_checked
    except OSError:
        return False


__all__ = ["History", "fold", "stale"]
