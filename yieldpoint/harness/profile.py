"""A portable, deterministic description of what a change needs from a host.

The profile is evidence, not a model choice. Hosts may map it to a local model,
an external router, or a person; Yieldpoint never sends it anywhere.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from ..core.policy import Policy
from ..core.verdict import Status
from .decisions import Choice, Score
from .routing import risk, tier
from .signals import Change, Signals, measure

ROUTING_PROFILE_SCHEMA_VERSION = 1
CAPABILITIES = frozenset({
    "tool_use", "strong_reasoning", "large_context", "code_generation",
    "multilingual_sdk", "human_review",
})
CHECKS = frozenset({
    "unit_tests", "package_consumer", "release_preflight", "integration_tests",
    "human_review",
})


@dataclass(frozen=True)
class RoutingProfile:
    """Versioned profile with JSON limited to portable primitive values."""

    data: Mapping[str, Any]

    @property
    def profile_id(self) -> str:
        return str(self.data["profile_id"])

    def to_dict(self) -> dict[str, Any]:
        return dict(self.data)


@dataclass(frozen=True)
class ProfileContext:
    """Optional measured inputs, grouped to keep the public API compact."""

    signals: Signals | None = None
    verdict: Mapping[str, Any] | None = None
    baseline_findings: int = 0
    introduced_findings: int | None = None
    graph: Any = None


def build_profile(
    change: Change,
    policy: Policy | str | dict | None = None,
    *,
    context: ProfileContext = ProfileContext(),
) -> RoutingProfile:
    """Build a profile without reading intent or contacting a provider."""
    resolved = Policy.load(policy)
    found = context.signals or measure(change, resolved, context.graph)
    risk_decision = risk(change, resolved, signals=found)
    tier_decision = tier(change, resolved, signals=found)
    status = _status(context.verdict)
    introduced = _introduced_findings(context)
    required, capabilities, suggested = _requirements(change.path, found, risk_decision, tier_decision, status)
    payload = {
        "schema_version": ROUTING_PROFILE_SCHEMA_VERSION,
        "risk": risk_decision.to_dict(),
        "tier": tier_decision.to_dict(),
        "coverage": _coverage(change.path, found),
        "change": {
            "files": 1, "added_lines": found.added_lines, "deleted_lines": found.removed_lines,
            "structural": found.structural, "baseline_findings": max(0, context.baseline_findings),
            "introduced_findings": max(0, introduced),
        },
        "verification": {
            "status": status, "required": sorted(required),
            "findings": _finding_rules(context.verdict), "repair_attempt": 0, "loop_tripped": False,
        },
        "requirements": {
            "capabilities": sorted(capabilities),
            "minimum_context_window": "large" if "large_context" in capabilities else "standard",
            "suggested_policy": suggested, "may_skip_model": tier_decision.value == "none",
        },
        "handoff": {
            "max_model_switches": resolved.routing_session.max_model_switches,
            "switch_allowed_now": False,
            "reason": "model selection is sticky until a configured checkpoint",
            "capsule_max_chars": resolved.routing_session.capsule_max_chars,
        },
    }
    return RoutingProfile({**payload, "profile_id": _profile_id(payload)})


def _introduced_findings(context: ProfileContext) -> int:
    if context.introduced_findings is not None:
        return max(0, context.introduced_findings)
    return len(context.verdict.get("findings", ())) if context.verdict else 0


def _requirements(path: str, signals: Signals, score: Score, choice: Choice, status: str) -> tuple[set[str], set[str], str]:
    if signals.touches_protected_test or status == Status.BLOCK.value:
        return {"human_review"}, {"human_review"}, "human_before_land"
    release = _is_release_path(path)
    if release:
        return {"unit_tests", "package_consumer", "release_preflight"}, {"multilingual_sdk", "tool_use", "strong_reasoning"}, "sticky_capable"
    if not signals.analysable:
        return {"unit_tests"}, {"large_context", "strong_reasoning"}, "sticky_capable"
    if status in (Status.REPAIR.value, Status.ESCALATE.value) or score.value in ("high", "critical"):
        return {"unit_tests"}, {"tool_use", "strong_reasoning"}, "sticky_capable"
    if choice.value == "none":
        return {"unit_tests"}, set(), "no_model_after_verify"
    return {"unit_tests"}, {"code_generation"}, "sticky_standard"


def _coverage(path: str, signals: Signals) -> dict[str, Any]:
    language = _language(path)
    return {
        "analysed_paths": [path] if signals.analysable else [],
        "unverified_paths": [] if signals.analysable else [path],
        "languages": [language], "exact_analysis": signals.analysable,
    }


def _language(path: str) -> str:
    suffix = path.rsplit(".", 1)[-1].lower() if "." in path else "unknown"
    return {"py": "python", "js": "javascript", "ts": "typescript", "java": "java"}.get(suffix, "unknown")


def _is_release_path(path: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    return "sdk" in parts or any(part in {"release", "releases", ".github"} for part in parts)


def _status(verdict: Mapping[str, Any] | None) -> str:
    value = verdict.get("status") if verdict else Status.UNVERIFIED.value
    return value if value in {item.value for item in Status} else Status.UNVERIFIED.value


def _finding_rules(verdict: Mapping[str, Any] | None) -> list[str]:
    if not verdict:
        return []
    return sorted({str(item.get("rule")) for item in verdict.get("findings", ()) if isinstance(item, Mapping) and item.get("rule")})


def _profile_id(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = ["RoutingProfile", "ProfileContext", "build_profile", "ROUTING_PROFILE_SCHEMA_VERSION", "CAPABILITIES", "CHECKS"]
