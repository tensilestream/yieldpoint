"""Deciding how much model a piece of work actually needs.

An agent loop that sends every edit to its most capable model pays the same
price for renaming a variable as for restructuring a module. Choosing between
them is itself usually done by asking a model, which adds a round trip to save
one — and answers differently on Tuesday.

Most of that choice is computable. A change with no structural effect, low
churn and no protected test in sight is not a hard problem, whatever it is
about; one that rewrites assertions in a protected suite is, whatever its size.

Two decisions live here, both derived from :mod:`signals` and both free:

``risk``  — an ordered Score, which is what a gate keys on.
``tier``  — a Choice of how much model to spend, which is what a router keys on.

**Where this stops.** These read the shape of a change, never its meaning. A
one-line edit to a payments calculation is ``trivial`` by every measure here and
is not a trivial change. So the tier is a *ceiling on cheapness*, not a
judgement of importance: it says when the expensive model is unnecessary, and
never claims a change is unimportant. A harness with its own reasons to escalate
should escalate.
"""

from __future__ import annotations

from .decisions import Choice, Score
from .signals import Change, Signals, measure

RISK_LEVELS = ("trivial", "low", "moderate", "high", "critical")

TIERS = ("none", "small", "standard", "capable", "human")
"""``none`` means no model call is needed at all — the change is mechanical and
already verified. ``human`` means do not spend a model on this; ask."""

#: Churn above which a change stops being a local edit.
SMALL_CHURN = 12
MODERATE_CHURN = 60
LARGE_CHURN = 250


def risk(change: Change, policy=None, signals: Signals | None = None) -> Score:
    """How much could this change break? An ordered, reproducible answer."""
    found = signals or measure(change, policy)
    level, reason = _risk_level(found)
    return Score(
        question="risk",
        value=level,
        levels=RISK_LEVELS,
        reason=reason,
        signals=found.to_dict(),
    )


def _risk_level(s: Signals) -> tuple[str, str]:
    if s.touches_protected_test:
        return "critical", "edits a protected test file, where a weakening hides itself"
    if s.touches_generated:
        return "high", "edits generated output, which the next build discards"
    if s.parses is False:
        return "high", "the result does not parse"
    if not s.analysable:
        return "moderate", "no exact analyser for this file type; risk is unmeasured"
    if s.churn >= LARGE_CHURN:
        return "high", f"{s.churn} lines changed is past reviewing in one sitting"
    if s.structural and s.churn >= MODERATE_CHURN:
        return "moderate", f"structural change across {s.churn} lines"
    if s.structural:
        return "low", "changes what the module defines or imports"
    if s.churn > SMALL_CHURN:
        return "low", f"{s.churn} lines changed, none of it structural"
    return "trivial", "small, and changes nothing the module exposes"


def tier(
    change: Change,
    policy=None,
    signals: Signals | None = None,
    *,
    verified: bool | None = None,
) -> Choice:
    """How much model this work needs.

    ``verified`` is the result of actually checking the change, when the caller
    already has one. A change that has been verified clean and is mechanical
    needs no further model call at all, which is the only tier that saves a
    whole round trip rather than trading one model for a cheaper one.
    """
    found = signals or measure(change, policy)
    level = _risk_level(found)[0]
    choice, reason = _tier_for(level, found, verified)
    return Choice(
        question="tier",
        value=choice,
        options=TIERS,
        reason=reason,
        signals={**found.to_dict(), "risk": level, "verified": verified},
    )


def _tier_for(level: str, s: Signals, verified: bool | None) -> tuple[str, str]:
    if level == "critical":
        return "human", "a protected test changed; a person should look before this lands"
    if level == "high":
        return "capable", "large or unparseable; the cheap model will not hold it"
    if verified and not s.structural and s.churn <= SMALL_CHURN:
        return "none", "verified clean, mechanical, and small — no model call needed"
    if level == "moderate":
        return "capable", "structural change of real size"
    if level == "low":
        return "standard", "a normal edit"
    return "small", "cosmetic and local; the cheapest model is enough"


def model_for(decision: Choice, tiers: dict[str, str]) -> str | None:
    """Map a tier onto a caller's model names. ``None`` means make no call."""
    if decision.value in ("none", "human"):
        return None
    return tiers.get(decision.value)


__all__ = ["risk", "tier", "model_for", "RISK_LEVELS", "TIERS"]
