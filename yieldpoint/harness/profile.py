"""A portable, deterministic description of what a change needs from a host.

The profile is evidence, not a model choice. Hosts may map it to a local model,
an external router, or a person; Yieldpoint never sends it anywhere.

The ``handoff`` block carries every bound the policy sets, rather than leaving
them in Python. A Node or Java host receives only this document, so a limit kept
behind in the engine is a limit those hosts cannot honour — and a rule two of
the three languages cannot see is a rule that has already drifted.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Mapping, Sequence

from ..core.policy import Policy
from ..core.routingsession import CHECKS, EVENTS
from ..core.verdict import Status
from .decisions import Choice, Score
from .pacing import pace
from .routing import risk, tier
from .signals import Change, Signals, measure

ROUTING_PROFILE_SCHEMA_VERSION = 1
CAPABILITIES = frozenset({
    "tool_use", "strong_reasoning", "large_context", "code_generation",
    "multilingual_sdk", "human_review",
})

#: Extension to language, for reporting which part of a change was analysed
#: exactly. A suffix absent here is reported as ``unknown`` rather than guessed.
LANGUAGES = {
    "py": "python", "js": "javascript", "mjs": "javascript", "cjs": "javascript",
    "jsx": "javascript", "ts": "typescript", "tsx": "typescript", "java": "java",
    "kt": "kotlin", "go": "go", "rs": "rust", "cs": "csharp", "rb": "ruby",
    "php": "php", "swift": "swift", "c": "c", "h": "c", "cc": "cpp",
    "cpp": "cpp", "hpp": "cpp",
}


@dataclass(frozen=True)
class RoutingProfile:
    """Versioned profile with JSON limited to portable primitive values."""

    data: Mapping[str, Any]

    @property
    def profile_id(self) -> str:
        return str(self.data["profile_id"])

    def to_dict(self) -> dict[str, Any]:
        return dict(self.data)


def validate_profile(source: Mapping[str, Any]) -> RoutingProfile:
    """Validate profile transport received from a Python, Node, or Java host.

    The digest is recomputed rather than trusted. A profile whose body no longer
    hashes to its own ``profile_id`` has been edited in transit or paired with
    the wrong capsule, and both are exactly what the identifier exists to catch.
    """
    if source.get("schema_version") != ROUTING_PROFILE_SCHEMA_VERSION:
        raise ValueError("unsupported routing profile schema")
    if not isinstance(source.get("profile_id"), str) or not source["profile_id"]:
        raise ValueError("routing profile is missing profile_id")
    for key in ("coverage", "requirements", "handoff", "verification"):
        if not isinstance(source.get(key), Mapping):
            raise ValueError(f"routing profile is missing {key}")
    if not isinstance(source["requirements"].get("capabilities"), list):
        raise ValueError("routing profile capabilities must be a list")
    body = {key: value for key, value in source.items() if key != "profile_id"}
    if _profile_id(body) != source["profile_id"]:
        raise ValueError("routing profile digest does not match its contents")
    return RoutingProfile(dict(source))


@dataclass(frozen=True)
class ProfileContext:
    """Optional measured inputs, grouped to keep the public API compact."""

    signals: Signals | None = None
    verdict: Mapping[str, Any] | None = None
    baseline_findings: int = 0
    introduced_findings: int | None = None
    repair_attempt: int = 0
    loop_tripped: bool = False
    graph: Any = None


@dataclass(frozen=True)
class _Evidence:
    """One file's measured facts. Grouped so the decision rows take one argument."""

    path: str
    signals: Signals
    risk: Score
    tier: Choice


def build_profile(
    change: Change | Sequence[Change],
    policy: Policy | str | dict | None = None,
    *,
    context: ProfileContext = ProfileContext(),
) -> RoutingProfile:
    """Build a profile without reading intent or contacting a provider.

    ``change`` is one :class:`Change` or the whole change set. A task usually
    spans several files, and a profile describing only one of them understates
    what the work needs: the riskiest file decides the tier, every file's
    requirements accumulate, and the change-budget pace is only meaningful
    against the real file count.
    """
    changes = (change,) if isinstance(change, Change) else tuple(change)
    if not changes:
        raise ValueError("a routing profile needs at least one change")
    resolved = Policy.load(policy)
    found = _measure_all(changes, resolved, context)
    evidence = tuple(
        _Evidence(item.path, signals,
                  risk(item, resolved, signals=signals),
                  tier(item, resolved, signals=signals))
        for item, signals in zip(changes, found)
    )
    payload = _payload(evidence, found, resolved, context)
    return RoutingProfile({**payload, "profile_id": _profile_id(payload)})


def _payload(evidence: tuple[_Evidence, ...], found: tuple[Signals, ...],
             policy: Policy, context: ProfileContext) -> dict[str, Any]:
    """Assemble the document, aggregating the per-file evidence into one task."""
    status = _status(context.verdict)
    required, capabilities, suggested = _requirements(
        evidence, status, policy.routing_session.required_checks)
    return {
        "schema_version": ROUTING_PROFILE_SCHEMA_VERSION,
        "risk": max(evidence, key=lambda item: item.risk.rank).risk.to_dict(),
        "tier": max(evidence, key=lambda item: _tier_rank(item.tier)).tier.to_dict(),
        "coverage": _coverage(evidence),
        "change": {
            "files": len(evidence),
            "added_lines": sum(item.added_lines for item in found),
            "deleted_lines": sum(item.removed_lines for item in found),
            "structural": any(item.structural for item in found),
            "baseline_findings": max(0, context.baseline_findings),
            "introduced_findings": max(0, _introduced_findings(context)),
        },
        "verification": {
            "status": status, "required": sorted(required),
            "findings": _finding_rules(context.verdict),
            "repair_attempt": max(0, context.repair_attempt),
            "loop_tripped": bool(context.loop_tripped),
        },
        "requirements": {
            "capabilities": sorted(capabilities),
            "minimum_context_window": "large" if "large_context" in capabilities else "standard",
            "suggested_policy": suggested,
            "may_skip_model": all(item.tier.value == "none" for item in evidence),
        },
        "handoff": _handoff(policy),
        "pace": _pace(policy, found, len(evidence), context.verdict),
    }


def _measure_all(changes: tuple[Change, ...], policy: Policy,
                 context: ProfileContext) -> tuple[Signals, ...]:
    """Measure each file, reusing signals a caller already computed for one."""
    if len(changes) == 1 and context.signals is not None:
        return (context.signals,)
    return tuple(measure(item, policy, context.graph) for item in changes)


def _tier_rank(choice: Choice) -> int:
    """Where a tier sits on its own scale; -1 keeps an unknown tier lowest."""
    try:
        return choice.options.index(choice.value)
    except ValueError:
        return -1


def _handoff(policy: Policy) -> dict[str, Any]:
    """Publish every bound the gate applies, so all three SDKs apply the same."""
    session = policy.routing_session
    return {
        "max_model_switches": session.max_model_switches,
        "switch_allowed_now": False,
        "reason": "model selection is sticky until a configured checkpoint",
        "capsule_max_chars": session.capsule_max_chars,
        "checkpoint_events": sorted(session.checkpoint_events),
        "max_overhead_fraction": session.router_overhead_fraction,
        "allow_unverified": session.allow_unverified,
    }


def _pace(policy: Policy, signals: tuple[Signals, ...], files: int,
          verdict: Mapping[str, Any] | None) -> dict[str, Any]:
    """Surface budget pressure in the profile, at admission rather than at stop
    time. Advisory only: nothing in the handoff gate reads it."""
    rules = _finding_rules(verdict)
    decision = pace(SimpleNamespace(findings=[SimpleNamespace(rule=rule) for rule in rules]),
                    sum(item.added_lines for item in signals), files,
                    policy.structure.max_change_lines)
    return {"value": decision.value, "reason": decision.reason,
            "signals": {"budget_used": decision.signals.get("budget_used", 0.0)}}


def _introduced_findings(context: ProfileContext) -> int:
    if context.introduced_findings is not None:
        return max(0, context.introduced_findings)
    return len(context.verdict.get("findings", ())) if context.verdict else 0


def _requirements(evidence: tuple[_Evidence, ...], status: str,
                  checks: Mapping[str, tuple[str, ...]]) -> tuple[set[str], set[str], str]:
    """The decision table, in the order the rows are written.

    Rows accumulate rather than replace, both within a file and across the
    change set: an unanalysable file inside an SDK needs a large context *and*
    cross-language knowledge, and a task containing one risky file is a risky
    task. Reporting either weaker requirement would understate the work. The
    *policy label* is still first-match, because a task has one shape.
    """
    if status == Status.BLOCK.value or any(
            item.signals.touches_protected_test for item in evidence):
        return {"human_review"}, {"human_review"}, "human_before_land"
    required: set[str] = {"unit_tests"}
    capabilities: set[str] = set()
    suggested = ""
    for item in evidence:
        rows_required, rows_capabilities, label = _rows(item, status, checks)
        required |= rows_required
        capabilities |= rows_capabilities
        suggested = suggested or label
    if suggested:
        return required, capabilities, suggested
    if all(item.tier.value == "none" for item in evidence):
        return required, capabilities, "no_model_after_verify"
    return required, capabilities | {"code_generation"}, "sticky_standard"


def _rows(evidence: _Evidence, status: str,
          checks: Mapping[str, tuple[str, ...]]) -> tuple[set[str], set[str], str]:
    """The capability rows for one file. Each adds what it needs."""
    required: set[str] = set()
    capabilities: set[str] = set()
    suggested = ""
    if not evidence.signals.analysable:
        capabilities |= {"large_context", "strong_reasoning"}
        suggested = "sticky_capable"
    if _is_release_path(evidence.path):
        required |= set(checks.get("cross_sdk_release", ()))
        capabilities |= {"multilingual_sdk", "tool_use", "strong_reasoning"}
        suggested = suggested or "sticky_capable"
    if _needs_reasoning(evidence, status):
        capabilities |= {"tool_use", "strong_reasoning"}
        suggested = suggested or "sticky_capable"
    return required, capabilities, suggested


def _needs_reasoning(evidence: _Evidence, status: str) -> bool:
    """A failed repair or a structurally risky change earns the capable tier."""
    return (status in (Status.REPAIR.value, Status.ESCALATE.value)
            or evidence.risk.value in ("high", "critical"))


def _coverage(evidence: tuple[_Evidence, ...]) -> dict[str, Any]:
    """Which files were analysed exactly, and which the engine could not read.

    ``exact_analysis`` is true only when every file was analysable: one file the
    engine could not read makes the whole set partially unverified, and saying
    otherwise is the clean-result-from-no-analysis failure this contract exists
    to prevent.
    """
    analysed = sorted(item.path for item in evidence if item.signals.analysable)
    unverified = sorted(item.path for item in evidence if not item.signals.analysable)
    return {
        "analysed_paths": analysed, "unverified_paths": unverified,
        "languages": sorted({_language(item.path) for item in evidence}),
        "exact_analysis": not unverified,
    }


def _language(path: str) -> str:
    suffix = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return LANGUAGES.get(suffix, "unknown")


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


__all__ = ["RoutingProfile", "ProfileContext", "build_profile", "validate_profile",
           "ROUTING_PROFILE_SCHEMA_VERSION", "CAPABILITIES", "CHECKS", "EVENTS", "LANGUAGES"]
