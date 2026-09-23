"""CLI entry points for provider-neutral routing state.

They read and write JSON only; model names, credentials, and provider requests
stay outside Yieldpoint.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .core.policy import Policy
from .harness import (
    CapsuleInput, Change, HandoffRequest, ProfileContext, admit, build_profile,
    build_task_capsule, can_handoff, session_from, validate_profile,
)
from .routingledger import RoutingFact, record, summarise


def add_command(sub) -> None:
    """Register the three machine-readable routing lifecycle commands."""
    profile = sub.add_parser("assess-routing", help="build a provider-neutral routing profile")
    profile.add_argument("--path", help="single changed file; omit when using --diff")
    profile.add_argument("--before", default="")
    profile.add_argument("--after", default="")
    profile.add_argument("--diff", default="",
                         help="unified diff covering the whole change set")
    profile.add_argument("--policy")
    profile.add_argument("--root", default=".")
    profile.add_argument("--task", default="")
    profile.add_argument("--verdict", default="",
                         help="verdict JSON from `yieldpoint verify-change --json`")
    profile.add_argument("--repair-attempt", type=int, default=0)
    profile.add_argument("--loop-tripped", action="store_true")
    profile.set_defaults(handler=assess_command)

    capsule = sub.add_parser("build-capsule", help="build a bounded handoff capsule")
    capsule.add_argument("--profile", required=True)
    capsule.add_argument("--session", required=True)
    capsule.add_argument("--objective", required=True)
    capsule.add_argument("--acceptance", action="append", default=[])
    capsule.add_argument("--policy")
    capsule.add_argument("--root", default=".")
    capsule.set_defaults(handler=capsule_command)

    handoff = sub.add_parser("handoff-check", help="validate one model handoff")
    handoff.add_argument("--profile", required=True)
    handoff.add_argument("--session", required=True)
    handoff.add_argument("--event", required=True)
    handoff.add_argument("--capability", action="append", default=[])
    handoff.add_argument("--overhead", type=float, default=0.0,
                         help="estimated router and capsule input, as a fraction "
                              "of the task's model input")
    handoff.add_argument("--policy")
    handoff.add_argument("--root", default=".")
    handoff.set_defaults(handler=handoff_command)

    stats = sub.add_parser("routing-stats", help="show redacted local routing activity")
    stats.add_argument("--policy")
    stats.add_argument("--root", default=".")
    stats.set_defaults(handler=stats_command)


def assess_command(args) -> int:
    """Emit a profile from file transitions, without invoking a provider.

    ``--diff`` profiles a whole change set, which is usually what a task is;
    ``--path/--after`` profiles one file. A verdict is optional but
    load-bearing: without one the profile reports ``unverified``, which is the
    honest answer and also the one that refuses a handoff. Pass ``--verdict``
    to route on what verification actually found.
    """
    policy = Policy.load(args.policy)
    try:
        changes = _changes(args)
    except ValueError as exc:
        print(f"yieldpoint: {exc}", file=sys.stderr)
        return 2
    context = ProfileContext(
        verdict=json.loads(_read(args.verdict)) if args.verdict else None,
        repair_attempt=args.repair_attempt, loop_tripped=args.loop_tripped,
    )
    profile = build_profile(changes, policy, context=context).to_dict()
    record(RoutingFact("profile", profile), policy=policy, root=args.root)
    print(json.dumps(profile, indent=2, sort_keys=True))
    return 0


def capsule_command(args) -> int:
    """Emit a deterministic capsule for a matching profile/session pair."""
    profile, session = _documents(args)
    context = CapsuleInput(args.objective, tuple(args.acceptance))
    capsule = build_task_capsule(session, profile, context=context)
    policy = Policy.load(args.policy)
    record(RoutingFact("capsule", profile, session=session,
                       capsule_chars=len(json.dumps(capsule, sort_keys=True, separators=(",", ":")))),
           policy=policy, root=args.root)
    print(json.dumps(capsule, indent=2, sort_keys=True))
    return 0


def handoff_command(args) -> int:
    """Report whether an explicit checkpoint may change the selected model."""
    profile, raw_session = _documents(args)
    request = HandoffRequest(args.event, candidate_capabilities=frozenset(args.capability),
                             estimated_overhead_fraction=args.overhead)
    allowed, reason = can_handoff(session_from(raw_session), profile, request)
    policy = Policy.load(args.policy)
    record(RoutingFact("handoff", profile, session=raw_session, allowed=allowed,
                       event=args.event), policy=policy, root=args.root)
    print(json.dumps({"allowed": allowed, "reason": reason}, indent=2, sort_keys=True))
    return 0 if allowed else 3


def stats_command(args) -> int:
    """Print only counted routing metadata; the underlying ledger stays local."""
    print(json.dumps(summarise(Policy.load(args.policy), args.root), indent=2, sort_keys=True))
    return 0


def _documents(args) -> tuple[dict, dict]:
    """Read a profile/session pair, checking the profile has not been edited.

    Validating here rather than trusting the file is the point of the digest: a
    profile whose bounds were widened by hand is the one case where a gate that
    reads its limits from the document would otherwise be talked out of them.
    """
    return validate_profile(_json(args.profile)).to_dict(), _json(args.session)


def _json(path: str) -> dict:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _changes(args) -> tuple[Change, ...]:
    """Read the change set from a diff, or from one explicit file transition."""
    if args.diff:
        from .verify import states_in

        found = states_in(_read(args.diff) or "", args.root)
        if not found:
            raise ValueError(f"{args.diff} describes no file this engine can reconstruct")
        return tuple(Change(path, before, after, args.task)
                     for path, before, after in found)
    if not args.path or not args.after:
        raise ValueError("--path and --after are required unless --diff is given")
    return (Change(args.path, _read(args.before), _read(args.after), args.task),)


def _read(path: str) -> str | None:
    return Path(path).read_text(encoding="utf-8") if path else None


__all__ = ["add_command"]
