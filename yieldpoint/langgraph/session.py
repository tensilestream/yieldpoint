"""LangGraph-compatible admission and handoff nodes for sticky model routing."""

from __future__ import annotations

from typing import Any, Callable, Mapping

from ..core.policy import Policy
from ..harness import (
    Change, HandoffRequest, ProfileContext, admit, build_profile, can_handoff,
    session_from,
)
from ..routingledger import RoutingFact, record
from .node import ATTEMPTS_KEY, TRIPPED_KEY, VERDICT_KEY, verdict_from
from .router import ESCALATE

PROFILE_KEY = "yieldpoint_routing_profile"
SESSION_KEY = "yieldpoint_routing_session"
HANDOFF_EVENT_KEY = "yieldpoint_handoff_event"
OVERHEAD_KEY = "yieldpoint_estimated_overhead"


def make_admission_node(*, task_id: str, selected_model: str = "",
                        selection_source: str = "deterministic",
                        policy: Policy | str | dict | None = None) -> Callable[[Mapping[str, Any]], dict]:
    """Return a node that selects once and stores JSON-safe profile/session state.

    The verdict, repair count, and loop state already in graph state are read
    into the profile. Placed after a verify node, admission therefore routes on
    what verification found; placed before one, it reports ``unverified`` and
    the handoff gate refuses — which is the correct answer to a question asked
    before there was any evidence to answer it with.
    """
    resolved = Policy.load(policy)

    def admission(state: Mapping[str, Any]) -> dict:
        profile = build_profile(_change(state), resolved,
                                context=_context(state)).to_dict()
        session = admit(
            profile, task_id=task_id, selected_model=selected_model,
            selection_source=selection_source,
        )
        record(RoutingFact("admission", profile, session=session.to_dict()), policy=resolved,
               root=str(state.get("root", ".")))
        return {PROFILE_KEY: profile, SESSION_KEY: session.to_dict()}

    return admission


def _context(state: Mapping[str, Any]) -> ProfileContext:
    """Read verification evidence from graph state, if a verify node ran."""
    verdict = verdict_from(state, VERDICT_KEY).to_dict() if state.get(VERDICT_KEY) else None
    return ProfileContext(
        verdict=verdict,
        repair_attempt=int(state.get(ATTEMPTS_KEY, 0) or 0),
        loop_tripped=bool(state.get(TRIPPED_KEY)),
    )


def make_handoff_router(*, candidate_capabilities: frozenset[str],
                        on_allowed: str = "handoff", on_denied: str = ESCALATE) -> Callable[[Mapping[str, Any]], str]:
    """Route only an explicit, policy-bounded handoff to a host graph edge."""
    def route(state: Mapping[str, Any]) -> str:
        profile = state.get(PROFILE_KEY)
        session = state.get(SESSION_KEY)
        if not isinstance(profile, Mapping) or not isinstance(session, Mapping):
            return on_denied
        request = HandoffRequest(
            event=str(state.get(HANDOFF_EVENT_KEY, "")),
            candidate_capabilities=candidate_capabilities,
            estimated_overhead_fraction=float(state.get(OVERHEAD_KEY, 0.0) or 0.0),
        )
        allowed, _ = can_handoff(session_from(session), profile, request)
        return on_allowed if allowed else on_denied

    return route


def _change(state: Mapping[str, Any]) -> Change:
    changes = state.get("changes")
    if not isinstance(changes, list) or not changes or not isinstance(changes[0], Mapping):
        raise ValueError("admission requires one change in state['changes']")
    source = changes[0]
    path = str(source.get("path", ""))
    if not path:
        raise ValueError("admission change requires a path")
    return Change(path, source.get("before"), source.get("after"), str(state.get("task", "")))


__all__ = [
    "PROFILE_KEY", "SESSION_KEY", "HANDOFF_EVENT_KEY", "OVERHEAD_KEY",
    "make_admission_node", "make_handoff_router",
]
