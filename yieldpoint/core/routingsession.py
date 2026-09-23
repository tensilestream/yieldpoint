"""Configuration for context-safe, host-owned model routing.

This is intentionally separate from the risk thresholds: those describe a
change, while these bounds describe a task session and must never name a model
provider or executable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Checks a profile may require before a change is considered landable. Closed
#: so that a host reading the contract in another language can switch on it.
CHECKS = (
    "unit_tests", "package_consumer", "release_preflight", "integration_tests",
    "human_review",
)

#: Events that may open a handoff checkpoint. Which of them are *live* is
#: policy (``checkpoint_events``); this is only the spelling.
EVENTS = (
    "verification_failed", "repair_exhausted", "loop_tripped", "user_requested",
)

#: Named check sets a profile applies when a change matches that situation. A
#: team that releases differently overrides the list rather than the rule.
DEFAULT_REQUIRED_CHECKS = {
    "cross_sdk_release": ("unit_tests", "package_consumer", "release_preflight"),
}


@dataclass(frozen=True)
class RoutingSession:
    """Limits Yieldpoint emits for a host that routes model work.

    Disabled by default so existing middleware keeps its current behaviour.
    A host owns model names, credentials, and provider requests; this policy
    only supplies deterministic bounds for any such integration.

    Every bound here is copied into the profile's ``handoff`` block, because
    that block is the only thing a Node or Java host receives. A limit that
    stayed behind in Python would be a limit those hosts could not honour.
    """

    enabled: bool = False
    max_model_switches: int = 1
    capsule_max_chars: int = 12_000
    router_overhead_fraction: float = 0.05
    allow_unverified: bool = False
    """Whether a change no rule could analyse may still be handed to another
    model. Off by default: escalating on absent evidence spends a larger model
    to answer a question nobody asked it."""

    checkpoint_events: tuple[str, ...] = (
        "verification_failed", "repair_exhausted", "loop_tripped",
    )
    required_checks: dict[str, tuple[str, ...]] = field(
        default_factory=lambda: dict(DEFAULT_REQUIRED_CHECKS))


__all__ = ["RoutingSession", "CHECKS", "EVENTS", "DEFAULT_REQUIRED_CHECKS"]
