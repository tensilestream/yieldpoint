"""State transitions for one sticky model-selection session.

No provider is called here. A host records its selection and asks these pure
functions whether a checkpoint may hand work to a different model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

SESSION_SCHEMA_VERSION = 1
CHECKPOINTS = frozenset({
    "verification_failed", "repair_exhausted", "loop_tripped", "user_requested",
})


@dataclass(frozen=True)
class RoutingSession:
    """Portable task state; model names remain opaque host-owned labels."""

    task_id: str
    profile_id: str
    selected_model: str = ""
    selection_source: str = "deterministic"
    selection_reason: str = ""
    switch_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "routing_session_version": SESSION_SCHEMA_VERSION,
            "task_id": self.task_id,
            "profile_id": self.profile_id,
            "selected_model": self.selected_model,
            "selection_source": self.selection_source,
            "selection_reason": self.selection_reason,
            "switch_count": self.switch_count,
        }


@dataclass(frozen=True)
class HandoffRequest:
    """Evidence a host presents at an explicit model-switch checkpoint."""

    event: str
    selected_model: str = ""
    candidate_capabilities: frozenset[str] = frozenset()
    estimated_overhead_fraction: float = 0.0
    reason: str = ""


def admit(profile: Mapping[str, Any], *, task_id: str, selected_model: str = "",
          selection_source: str = "deterministic", selection_reason: str = "") -> RoutingSession:
    """Start a task. Selection occurs once; later work uses this session."""
    if not task_id or not str(profile.get("profile_id", "")):
        raise ValueError("task_id and profile.profile_id are required")
    if selection_source not in {"deterministic", "jev", "manual"}:
        raise ValueError("selection_source must be deterministic, jev, or manual")
    return RoutingSession(task_id, str(profile["profile_id"]), selected_model,
                          selection_source, selection_reason)


def can_handoff(session: RoutingSession, profile: Mapping[str, Any],
                request: HandoffRequest) -> tuple[bool, str]:
    """Return whether a single explicit checkpoint can switch models."""
    if request.event not in CHECKPOINTS:
        return False, f"{request.event!r} is not a supported handoff checkpoint"
    if session.profile_id != profile.get("profile_id"):
        return False, "session does not belong to this routing profile"
    handoff = profile.get("handoff", {})
    if session.switch_count >= int(handoff.get("max_model_switches", 0)):
        return False, "model-switch budget is exhausted"
    if request.event != "user_requested" and request.event not in CHECKPOINTS:
        return False, "normal work keeps the admitted model"
    required = set(profile.get("requirements", {}).get("capabilities", ()))
    if "human_review" in required:
        return False, "profile requires human review"
    missing = sorted(required - set(request.candidate_capabilities))
    if missing:
        return False, "candidate lacks required capability: " + ", ".join(missing)
    if not 0 <= request.estimated_overhead_fraction <= 0.20:
        return False, "routing overhead must be between 0 and 0.20"
    return True, "explicit checkpoint permits one model handoff"


def handoff(session: RoutingSession, profile: Mapping[str, Any],
            request: HandoffRequest) -> RoutingSession:
    """Return a new session after a permitted handoff; never mutate history."""
    allowed, detail = can_handoff(session, profile, request)
    if not allowed:
        raise ValueError(detail)
    return RoutingSession(
        session.task_id, session.profile_id, request.selected_model, session.selection_source,
        request.reason or detail, session.switch_count + 1,
    )


__all__ = ["RoutingSession", "HandoffRequest", "admit", "can_handoff", "handoff", "SESSION_SCHEMA_VERSION"]
