"""State transitions for one sticky model-selection session.

No provider is called here. A host records its selection and asks these pure
functions whether a checkpoint may hand work to a different model.

Every bound the gate applies is read from the profile's ``handoff`` block rather
than from a constant in this module, so the Node and Java gates — which receive
only the profile — apply the same limits from the same numbers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ..core.routingsession import EVENTS
from ..core.verdict import Status

SESSION_SCHEMA_VERSION = 1
CHECKPOINTS = frozenset(EVENTS)
"""Events a host may *spell*. Which of them are live is policy, carried in the
profile's ``handoff.checkpoint_events``."""

#: Verdicts that settle a task rather than opening one. Escalating after a pass
#: buys a second opinion on work that already verified; escalating after a block
#: routes around a human decision. Neither is a handoff worth a larger model.
SETTLED = frozenset({Status.PASS.value, Status.BLOCK.value})


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


def session_from(source: Mapping[str, Any]) -> RoutingSession:
    """Rehydrate portable session JSON; reject missing identity fields."""
    if source.get("routing_session_version") != SESSION_SCHEMA_VERSION:
        raise ValueError("unsupported routing session schema")
    return RoutingSession(
        task_id=_required(source, "task_id"), profile_id=_required(source, "profile_id"),
        selected_model=str(source.get("selected_model", "")),
        selection_source=str(source.get("selection_source", "deterministic")),
        selection_reason=str(source.get("selection_reason", "")),
        switch_count=int(source.get("switch_count", 0)),
    )


def _required(source: Mapping[str, Any], key: str) -> str:
    value = str(source.get(key, ""))
    if not value:
        raise ValueError(f"routing session is missing {key}")
    return value


def can_handoff(session: RoutingSession, profile: Mapping[str, Any],
                request: HandoffRequest) -> tuple[bool, str]:
    """Return whether a single explicit checkpoint can switch models.

    Every denial names the bound it failed, so a host that is refused does not
    have to guess which of six conditions it missed.
    """
    handoff_bounds = profile.get("handoff", {})
    if session.profile_id != profile.get("profile_id"):
        return False, "session does not belong to this routing profile"
    live = set(handoff_bounds.get("checkpoint_events", ())) & CHECKPOINTS
    if request.event not in live:
        return False, (
            f"{request.event!r} is not a configured handoff checkpoint; "
            f"policy allows {', '.join(sorted(live)) or 'none'}"
        )
    if session.switch_count >= int(handoff_bounds.get("max_model_switches", 0)):
        return False, "model-switch budget is exhausted"
    settled, detail = _settled(profile, handoff_bounds)
    if settled:
        return False, detail
    required = set(profile.get("requirements", {}).get("capabilities", ()))
    if "human_review" in required:
        return False, "profile requires human review"
    missing = sorted(required - set(request.candidate_capabilities))
    if missing:
        return False, "candidate lacks required capability: " + ", ".join(missing)
    ceiling = float(handoff_bounds.get("max_overhead_fraction", 0.0))
    if not 0 <= request.estimated_overhead_fraction <= ceiling:
        return False, (
            f"estimated routing overhead {request.estimated_overhead_fraction:.0%} "
            f"exceeds the {ceiling:.0%} budget"
        )
    return True, "explicit checkpoint permits one model handoff"


def _settled(profile: Mapping[str, Any], bounds: Mapping[str, Any]) -> tuple[bool, str]:
    """Refuse a handoff the verdict has already answered."""
    status = str(profile.get("verification", {}).get("status", Status.UNVERIFIED.value))
    if status in SETTLED:
        return True, f"a {status} verdict does not need another model"
    if status == Status.UNVERIFIED.value and not bounds.get("allow_unverified"):
        return True, (
            "the change is unverified, so there is no evidence a stronger model "
            "would help; set routing_session.allow_unverified to override"
        )
    return False, ""


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


__all__ = ["RoutingSession", "HandoffRequest", "admit", "session_from", "can_handoff",
           "handoff", "SESSION_SCHEMA_VERSION", "CHECKPOINTS", "SETTLED"]
