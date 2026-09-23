"""LangGraph-compatible admission and handoff nodes for sticky model routing."""

from __future__ import annotations

from typing import Any, Callable, Mapping

from ..core.policy import Policy
from ..harness import Change, HandoffRequest, admit, build_profile, can_handoff, session_from
from .router import ESCALATE

PROFILE_KEY = "yieldpoint_routing_profile"
SESSION_KEY = "yieldpoint_routing_session"
HANDOFF_EVENT_KEY = "yieldpoint_handoff_event"


def make_admission_node(*, task_id: str, selected_model: str = "",
                        selection_source: str = "deterministic",
                        policy: Policy | str | dict | None = None) -> Callable[[Mapping[str, Any]], dict]:
    """Return a node that selects once and stores JSON-safe profile/session state."""
    resolved = Policy.load(policy)

    def admission(state: Mapping[str, Any]) -> dict:
        change = _change(state)
        profile = build_profile(change, resolved).to_dict()
        session = admit(
            profile, task_id=task_id, selected_model=selected_model,
            selection_source=selection_source,
        )
        return {PROFILE_KEY: profile, SESSION_KEY: session.to_dict()}

    return admission


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
    "PROFILE_KEY", "SESSION_KEY", "HANDOFF_EVENT_KEY", "make_admission_node",
    "make_handoff_router",
]
