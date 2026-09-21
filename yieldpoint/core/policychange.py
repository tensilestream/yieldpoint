"""A change to the rules is a change worth reporting.

Making the policy visible — so a person can see what is enforced, and an agent
can tune it — hands an agent the cheapest possible route through any finding:
raise the limit until the finding disappears. That is the same act this package
exists to detect, one level up. A suite weakened to make a change pass and a
policy weakened to make a change pass differ only in which file was edited.

So the policy file is checked like any other file. The rule never blocks, on
purpose: a project must be able to change its own standards without a fight.
It must simply never do so silently, because a relaxed threshold in a config
diff is the single easiest thing for a reviewer to scroll past.

Only loosening is reported. Tightening a limit needs no defence.
"""

from __future__ import annotations

import json

from .verdict import Confidence, Finding, Status

POLICY_WEAKENED = "policy_weakened"

#: The policy file, by name. Matched on the basename so a repository that keeps
#: its config a directory up is still covered.
FILENAME = ".yieldpoint.json"

#: Settings where a larger number permits more code to pass.
_LIMITS = ("max_file_lines", "max_lines", "max_parameters", "max_nesting",
           "max_complexity", "max_added_lines", "max_change_lines")

#: How hard a severity pushes back. Absent or null is no rule at all, which is
#: why ``None`` sorts below every real severity rather than beside them.
_FORCE = {"block": 3, "escalate": 2, "repair": 1}

_PRESCRIPTION = (
    "If the new limit is right for this project, keep it and say why in the "
    "change. If it was raised to clear a finding, restore it and fix the code "
    "the finding named."
)


def _force(value) -> int:
    return _FORCE.get(value, 0) if isinstance(value, str) else 0


def _number(value) -> float:
    """``null`` is no limit at all, so it ranks above every finite one."""
    return float("inf") if value is None else float(value)


def _limits(was: dict, now: dict) -> list[str]:
    old, new = was.get("structure") or {}, now.get("structure") or {}
    found = []
    for name in _LIMITS:
        if name not in old and name not in new:
            continue
        before, after = _number(old.get(name)), _number(new.get(name))
        if after <= before:
            continue
        shown = "no limit" if new.get(name) is None else f"{new.get(name):,}"
        was_shown = "no limit" if old.get(name) is None else f"{old.get(name):,}"
        found.append(f"`structure.{name}` raised from {was_shown} to {shown}")
    return found


def _severities(was: dict, now: dict) -> list[str]:
    """Any severity that now pushes back less than it did, wherever it lives."""
    found = []
    for section in sorted(set(was) | set(now)):
        old, new = was.get(section), now.get(section)
        if not isinstance(old, dict) or not isinstance(new, dict):
            continue
        for key in sorted(set(old) | set(new)):
            if key.startswith("_") or not _force(old.get(key)):
                continue
            if _force(new.get(key)) < _force(old.get(key)):
                after = new.get(key) if new.get(key) else "off"
                found.append(f"`{section}.{key}` lowered from {old[key]} to {after}")
    return found


def _exclusions(was: dict, now: dict) -> list[str]:
    old = set((was.get("structure") or {}).get("exclude") or ())
    new = set((now.get("structure") or {}).get("exclude") or ())
    added = sorted(new - old)
    return [f"`structure.exclude` now skips {', '.join(added)}"] if added else []


def _accounting(was: dict, now: dict) -> list[str]:
    """Turning the ledger off is not a code change, but it is evidence removed."""
    old = (was.get("metrics") or {}).get("enabled", True)
    new = (now.get("metrics") or {}).get("enabled", True)
    return ["`metrics.enabled` switched off, so nothing records what ran"] \
        if old and not new else []


def _parse(text: str | None) -> dict | None:
    if text is None:
        return None
    try:
        loaded = json.loads(text)
    except (ValueError, UnicodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def check(before: str | None, after: str | None,
          path: str) -> tuple[list[Finding], list[str]]:
    """Report every way this edit loosened the rules. Never blocks."""
    if path.replace("\\", "/").rsplit("/", 1)[-1] != FILENAME:
        return [], []
    was, now = _parse(before), _parse(after)
    if now is None:
        return [], [f"{path}: not readable as a policy file"]
    if was is None:
        # A policy arriving whole has nothing to have been weakened from.
        return [], []

    losses = (_limits(was, now) + _severities(was, now)
              + _exclusions(was, now) + _accounting(was, now))
    return [Finding(
        rule=POLICY_WEAKENED, status=Status.REPAIR, file=path, line=1,
        detail=f"This change loosens the rules: {loss}.",
        prescription=_PRESCRIPTION, confidence=Confidence.EXACT,
    ) for loss in losses], []


__all__ = ["POLICY_WEAKENED", "FILENAME", "check"]
