"""Bounded context handoff that preserves facts, not transcripts or secrets."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class CapsuleInput:
    """Host-owned facts to retain across one explicit model handoff."""

    objective: str
    acceptance_criteria: tuple[str, ...] = ()
    verdict: Mapping[str, Any] | None = None
    changed_paths: tuple[str, ...] = ()
    diff_excerpt: str = ""
    test_outcomes: tuple[str, ...] = ()
    completed_actions: tuple[str, ...] = ()


def build_task_capsule(session: Mapping[str, Any], profile: Mapping[str, Any], *,
                       context: CapsuleInput) -> dict[str, Any]:
    """Return a deterministic, size-bounded transfer document for one handoff."""
    if session.get("profile_id") != profile.get("profile_id"):
        raise ValueError("session does not belong to this routing profile")
    capsule = {
        "schema_version": 1,
        "task_id": session.get("task_id", ""),
        "profile_id": profile.get("profile_id", ""),
        "objective": context.objective,
        "acceptance_criteria": list(context.acceptance_criteria),
        "selection": {key: session.get(key, "") for key in (
            "selected_model", "selection_source", "selection_reason", "switch_count")},
        "changed_paths": sorted(context.changed_paths),
        "verification": _verification(context.verdict),
        "test_outcomes": list(context.test_outcomes),
        "completed_actions": list(context.completed_actions),
        "diff_excerpt": context.diff_excerpt,
        "unknowns": list(profile.get("coverage", {}).get("unverified_paths", [])),
        "truncated": [],
    }
    return _bound(capsule, int(profile.get("handoff", {}).get("capsule_max_chars", 12_000)))


def _verification(verdict: Mapping[str, Any] | None) -> dict[str, Any]:
    if not verdict:
        return {"status": "unverified", "findings": [], "prescription": ""}
    findings = [
        {key: item.get(key, "") for key in ("file", "line", "rule", "detail", "prescription")}
        for item in verdict.get("findings", ()) if isinstance(item, Mapping)
    ]
    return {"status": verdict.get("status", "unverified"), "findings": findings,
            "prescription": verdict.get("prescription", "")}


def _bound(capsule: dict[str, Any], maximum: int) -> dict[str, Any]:
    maximum = max(1_000, min(maximum, 24_000))
    for key in ("diff_excerpt", "test_outcomes", "completed_actions"):
        if len(_encoded(capsule)) <= maximum:
            break
        value = capsule[key]
        capsule[key] = "" if isinstance(value, str) else []
        capsule["truncated"].append(key)
    if len(_encoded(capsule)) > maximum:
        raise ValueError("objective, acceptance criteria, and findings exceed capsule limit")
    capsule["digest"] = "sha256:" + hashlib.sha256(_encoded(capsule).encode()).hexdigest()
    return capsule


def _encoded(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


__all__ = ["CapsuleInput", "build_task_capsule"]
