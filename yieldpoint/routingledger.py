"""Local, redacted accounting for provider-neutral routing decisions.

Routing activity is deliberately not a verification :class:`Event`: combining
the two would change verdict totals and would put a new shape into the
context-compaction records.  This ledger therefore shares the proven atomic
append machinery, but stores only bounded operational facts.  It never stores
model names, prompts, diffs, credentials, provider responses, or capsules.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .ledger import MAX_LINE_BYTES, _append, _prepare, _rotate
from .recording import enabled, path_for

DEFAULT_PATH = ".yieldpoint/routing.jsonl"
KINDS = frozenset({"profile", "admission", "capsule", "handoff"})


@dataclass(frozen=True)
class RoutingFact:
    """One bounded fact about routing; deliberately carries no content."""

    kind: str
    profile: Mapping[str, Any]
    session: Mapping[str, Any] | None = None
    allowed: bool | None = None
    event: str = ""
    capsule_chars: int = 0


def path_for_routing(policy, root: str | Path = ".") -> Path:
    """Return a sibling of the normal local ledger, not a provider endpoint."""
    return path_for(policy, root).with_name(Path(DEFAULT_PATH).name)


def record(fact: RoutingFact, *, policy, root: str | Path = ".") -> bool:
    """Append one redacted routing fact, without affecting a routing decision."""
    if fact.kind not in KINDS or not enabled(policy):
        return False
    try:
        payload = _payload(fact)
        line = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        if len(line.encode("utf-8")) > MAX_LINE_BYTES:
            return False
        target = path_for_routing(policy, root)
        _prepare(target.parent)
        _append(target, line + "\n")
        _rotate(target)
        return True
    except (OSError, TypeError, ValueError):
        return False


def _payload(fact: RoutingFact) -> dict[str, Any]:
    source = fact.session or {}
    tier = fact.profile.get("tier", {})
    payload = {
        "at": int(time.time()), "kind": fact.kind,
        "profile_id": str(fact.profile.get("profile_id", ""))[:80],
        "tier": str(tier.get("value", "") if isinstance(tier, Mapping) else "")[:32],
        "selection_source": str(source.get("selection_source", ""))[:24],
        "switch_count": max(0, int(source.get("switch_count", 0) or 0)),
    }
    if fact.allowed is not None:
        payload["allowed"] = bool(fact.allowed)
    if fact.event:
        payload["event"] = fact.event[:40]
    if fact.capsule_chars:
        payload["capsule_chars"] = max(0, int(fact.capsule_chars))
    return payload


def summarise(policy, root: str | Path = ".") -> dict[str, Any]:
    """Return measured routing counts from valid local lines only."""
    events = _events(path_for_routing(policy, root))
    handoffs = [item for item in events if item["kind"] == "handoff"]
    sources: dict[str, int] = {}
    for item in events:
        source = item.get("selection_source", "")
        if source:
            sources[source] = sources.get(source, 0) + 1
    return {
        "events": len(events),
        "profiles": sum(item["kind"] == "profile" for item in events),
        "admissions": sum(item["kind"] == "admission" for item in events),
        "capsules": sum(item["kind"] == "capsule" for item in events),
        "capsule_chars": sum(int(item.get("capsule_chars", 0)) for item in events),
        "handoffs": len(handoffs),
        "handoffs_allowed": sum(item.get("allowed") is True for item in handoffs),
        "handoffs_denied": sum(item.get("allowed") is False for item in handoffs),
        "selection_sources": dict(sorted(sources.items())),
    }


def _events(path: Path) -> list[dict[str, Any]]:
    out = []
    for candidate in (Path(str(path) + ".1"), path):
        try:
            lines = candidate.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for line in lines:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict) and value.get("kind") in KINDS:
                out.append(value)
    return out


__all__ = ["DEFAULT_PATH", "RoutingFact", "path_for_routing", "record", "summarise"]
