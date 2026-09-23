"""Configuration for context-safe, host-owned model routing.

This is intentionally separate from the risk thresholds: those describe a
change, while these bounds describe a task session and must never name a model
provider or executable.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RoutingSession:
    """Limits Yieldpoint emits for a host that routes model work.

    Disabled by default so existing middleware keeps its current behaviour.
    A host owns model names, credentials, and provider requests; this policy
    only supplies deterministic bounds for any such integration.
    """

    enabled: bool = False
    max_model_switches: int = 1
    capsule_max_chars: int = 12_000
    router_overhead_fraction: float = 0.05
    allow_unverified: bool = False
    checkpoint_events: tuple[str, ...] = (
        "verification_failed", "repair_exhausted", "loop_tripped",
    )


__all__ = ["RoutingSession"]
