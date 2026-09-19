"""Typed answers for an agent loop to act on, instead of prose to re-read.

The expensive part of an agent loop is not usually the work — it is asking a
language model questions that are not language questions. *How risky is this
edit? Is this big enough to need the capable model? Should this tool call run?*
Each costs a round trip, returns a paragraph, and answers differently next time.

Those are decisions, and most of them can be computed. This module is the shape
of a computed one:

    Choice  — pick one option from a fixed set
    Score   — place something on an ordered scale
    Gate    — allow or deny

Every decision carries the ``signals`` it was derived from, so a harness can log
why it routed a request without asking anything to explain itself.

**These are certainties, not estimates.** A model that classifies returns a
probability and is sometimes wrong; these are read off the syntax tree, so they
are exactly right about what they measure and silent about everything else. That
is the trade: narrower than a classifier, and reproducible. A decision this
module cannot make honestly is returned as ``unknown`` rather than guessed — an
agent that knows it was not told can ask a model, which is the correct fallback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

#: Incremented on any breaking change to the serialised decision shape. Separate
#: from the verdict's version because the two are consumed by different code and
#: should be able to move independently.
DECISION_SCHEMA_VERSION = 1

UNKNOWN = "unknown"
"""No rule could answer. Not a default answer — an admission, so the caller can
fall back to a model rather than act on a guess."""


@dataclass(frozen=True)
class Decision:
    """One answer, with the evidence behind it."""

    question: str
    value: Any
    reason: str = ""
    signals: Mapping[str, Any] = field(default_factory=dict)

    @property
    def known(self) -> bool:
        return self.value is not UNKNOWN and self.value is not None

    def to_dict(self) -> dict:
        return {
            "schema_version": DECISION_SCHEMA_VERSION,
            "question": self.question,
            "value": self.value,
            "reason": self.reason,
            "certain": self.known,
            "signals": dict(self.signals),
        }


@dataclass(frozen=True)
class Choice(Decision):
    """One option from a fixed set. ``options`` is part of the contract."""

    options: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {**super().to_dict(), "options": list(self.options)}


@dataclass(frozen=True)
class Score(Decision):
    """A position on an ordered scale, with the scale attached.

    The label matters more than the number: a harness routing on "moderate"
    keeps working when the scale gains a level, and one routing on ``2`` does
    not.
    """

    levels: tuple[str, ...] = ()

    @property
    def rank(self) -> int:
        try:
            return self.levels.index(self.value)
        except ValueError:
            return -1

    def at_least(self, level: str) -> bool:
        try:
            return self.rank >= self.levels.index(level)
        except ValueError:
            return False

    def to_dict(self) -> dict:
        return {**super().to_dict(), "levels": list(self.levels), "rank": self.rank}


@dataclass(frozen=True)
class Gate(Decision):
    """Allow or deny, where deny carries what to do instead."""

    prescription: str = ""

    @property
    def allowed(self) -> bool:
        return self.value is True

    def to_dict(self) -> dict:
        return {**super().to_dict(), "prescription": self.prescription}


def unknown(question: str, reason: str) -> Decision:
    """Say so, rather than defaulting.

    Returning a plausible answer here is the failure mode worth designing
    against: a harness cannot tell a computed answer from a fallback, so it
    stops being able to trust any of them.
    """
    return Decision(question=question, value=UNKNOWN, reason=reason)


__all__ = [
    "Decision", "Choice", "Score", "Gate", "unknown",
    "UNKNOWN", "DECISION_SCHEMA_VERSION",
]
