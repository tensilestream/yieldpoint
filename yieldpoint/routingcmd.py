"""CLI entry points for provider-neutral routing state.

They read and write JSON only; model names, credentials, and provider requests
stay outside Yieldpoint.
"""

from __future__ import annotations

import json
from pathlib import Path

from .core.policy import Policy
from .harness import (
    CapsuleInput, Change, HandoffRequest, admit, build_profile,
    build_task_capsule, can_handoff, session_from,
)


def add_command(sub) -> None:
    """Register the three machine-readable routing lifecycle commands."""
    profile = sub.add_parser("assess-routing", help="build a provider-neutral routing profile")
    profile.add_argument("--path", required=True)
    profile.add_argument("--before", default="")
    profile.add_argument("--after", required=True)
    profile.add_argument("--policy")
    profile.add_argument("--task", default="")
    profile.set_defaults(handler=assess_command)

    capsule = sub.add_parser("build-capsule", help="build a bounded handoff capsule")
    capsule.add_argument("--profile", required=True)
    capsule.add_argument("--session", required=True)
    capsule.add_argument("--objective", required=True)
    capsule.add_argument("--acceptance", action="append", default=[])
    capsule.set_defaults(handler=capsule_command)

    handoff = sub.add_parser("handoff-check", help="validate one model handoff")
    handoff.add_argument("--profile", required=True)
    handoff.add_argument("--session", required=True)
    handoff.add_argument("--event", required=True)
    handoff.add_argument("--capability", action="append", default=[])
    handoff.set_defaults(handler=handoff_command)


def assess_command(args) -> int:
    """Emit a profile from file transitions, without invoking a provider."""
    policy = Policy.load(args.policy)
    change = Change(args.path, _read(args.before), _read(args.after), args.task)
    print(json.dumps(build_profile(change, policy).to_dict(), indent=2, sort_keys=True))
    return 0


def capsule_command(args) -> int:
    """Emit a deterministic capsule for a matching profile/session pair."""
    profile, session = _documents(args)
    context = CapsuleInput(args.objective, tuple(args.acceptance))
    print(json.dumps(build_task_capsule(session, profile, context=context), indent=2, sort_keys=True))
    return 0


def handoff_command(args) -> int:
    """Report whether an explicit checkpoint may change the selected model."""
    profile, raw_session = _documents(args)
    request = HandoffRequest(args.event, candidate_capabilities=frozenset(args.capability))
    allowed, reason = can_handoff(session_from(raw_session), profile, request)
    print(json.dumps({"allowed": allowed, "reason": reason}, indent=2, sort_keys=True))
    return 0 if allowed else 3


def _documents(args) -> tuple[dict, dict]:
    return _json(args.profile), _json(args.session)


def _json(path: str) -> dict:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _read(path: str) -> str | None:
    return Path(path).read_text(encoding="utf-8") if path else None


__all__ = ["add_command"]
