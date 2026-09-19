"""Conditional-edge routing.

The router reads the verdict a node placed in state and returns the edge name to
follow. Like the node it imports nothing from LangGraph — a conditional edge is
a callable returning a string.

Two escalations happen here rather than in the checker, because both are about
the *loop* rather than the change: a repair budget that has run out, and a loop
that has stopped making progress. Without them a ``repair`` verdict can cycle
forever, which is the failure this product exists to prevent.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from ..core.verdict import Status
from .breaker import HISTORY_KEY
from .node import ATTEMPTS_KEY, TRIPPED_KEY, VERDICT_KEY, verdict_from

PASS = Status.PASS.value
UNVERIFIED = Status.UNVERIFIED.value
REPAIR = Status.REPAIR.value
ESCALATE = Status.ESCALATE.value
BLOCK = Status.BLOCK.value

DEFAULT_MAX_REPAIRS = 3


def route_on_verdict(state: Mapping[str, Any]) -> str:
    """Route on the verdict, with the default repair budget applied."""
    return make_router()(state)


def make_router(
    *,
    max_repairs: int = DEFAULT_MAX_REPAIRS,
    verdict_key: str = VERDICT_KEY,
    on_exhausted: str = ESCALATE,
    on_stalled: str = ESCALATE,
    on_unverified: str = UNVERIFIED,
) -> Callable[[Mapping[str, Any]], str]:
    """Build a router.

    ``max_repairs`` bounds how many times a change may be sent back for repair
    before a human is asked. ``on_stalled`` fires when the loop detector sees the
    same proposal produce the same findings repeatedly — retrying that is pure
    token burn.

    ``on_unverified`` decides what happens when no rule could analyse the change
    at all — a TypeScript file today, or a file that failed to parse. It defaults
    to its own ``"unverified"`` edge, which means an unmapped graph raises instead
    of quietly treating an unanalysed change as a clean one. Point it at ``PASS``
    to accept unverified changes, or at ``ESCALATE`` to ask a human; both are
    reasonable, and the choice belongs to whoever owns the pipeline.
    """

    def route(state: Mapping[str, Any]) -> str:
        verdict = verdict_from(state, verdict_key)
        if verdict.status is Status.UNVERIFIED:
            return on_unverified
        if verdict.status is not Status.REPAIR:
            return verdict.status.value

        if state.get(TRIPPED_KEY):
            return on_stalled
        if int(state.get(ATTEMPTS_KEY, 0)) >= max_repairs:
            return on_exhausted
        return REPAIR

    return route


def repair_context(state: Mapping[str, Any], verdict_key: str = VERDICT_KEY) -> str:
    """The message to feed back to the model on a repair edge.

    Deterministic and free: it is assembled from the verdict, not generated, so a
    repair round costs no extra model call to explain itself.
    """
    verdict = verdict_from(state, verdict_key)
    if not verdict.findings:
        return ""
    attempt = int(state.get(ATTEMPTS_KEY, 1))
    header = (
        f"Your change was rejected by deterministic verification "
        f"(attempt {attempt}). Fix these and try again:"
    )
    return f"{header}\n\n{verdict.prescription}"


__all__ = [
    "route_on_verdict", "make_router", "repair_context",
    "PASS", "UNVERIFIED", "REPAIR", "ESCALATE", "BLOCK", "HISTORY_KEY",
]
