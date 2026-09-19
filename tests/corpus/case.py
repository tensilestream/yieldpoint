"""One corpus entry."""

from __future__ import annotations

from dataclasses import dataclass

TUNED = "tuned"
"""Used while fixing the checker. A pass proves the fix landed, nothing more."""

HOLDOUT = "holdout"
"""Written after the fixes and never consulted during them. These are the cases
that say something about generalisation, and the only ones worth quoting."""


@dataclass(frozen=True)
class Case:
    name: str
    before: str
    after: str
    provenance: str
    path: str = "tests/test_subject.py"


__all__ = ["Case", "TUNED", "HOLDOUT"]
