"""The PreToolUse hook command, and the bound on how often it may deny.

Split from ``commands.py`` for the reason that module's own rules give: a file
holding every command has more than one reason to change, and this one changes
whenever the gate's answer does.
"""

from __future__ import annotations

import json
import sys

from .core.policy import Policy
from .hook import (
    allow_notice, blocks, decision_json, evaluate, read_payload, render,
)

EXIT_OK, EXIT_ERROR = 0, 2


def _handoff(args) -> int | None:
    """Other hook events share this entry point; ``None`` means PreToolUse."""
    from .commands import stop_command

    if getattr(args, "stop", False):
        return stop_command(args)
    if getattr(args, "post", False):
        from .posthook import post_command
        return post_command(args)
    return None


def hook_command(args) -> int:
    routed = _handoff(args)
    if routed is not None:
        return routed

    from .ledger import Run, Timer, record_run as _record

    payload = read_payload(sys.stdin.read())
    with Timer() as timer:
        verdict, change = evaluate(payload, args.policy)

    policy = _hook_policy(args)

    if change.usable:
        _record(
            verdict,
            Run("hook", len(change.before or "") + len(change.after or ""),
                 timer.elapsed_ms),
            policy,
        )

    return _hook_response(verdict, change, args,
                          _loop_state(verdict, change, policy, args, payload))


def _loop_state(verdict, change, policy, args, payload) -> str:
    """Track the run of identical denials, and say when it has gone on too long.

    Returns the stand-down notice, or ``""`` to answer as normal.
    """
    from . import editloop

    root = getattr(args, "root", ".")
    if not (blocks(verdict, policy) and not args.advisory):
        if change.usable:
            editloop.progressed(change.path, root=root)
        return ""
    session = str(payload.get("session_id") or payload.get("sessionId") or "")
    return editloop.release(verdict, change, policy, root, session)


def _hook_response(verdict, change, args, release: str) -> int:
    """Say allow or deny, in whichever form the host asked for.

    ``release`` is non-empty when the edit-loop breaker has stood the gate down:
    the finding is real and unwaived, but repeating the same denial has stopped
    being useful, so it is handed to the stop gate instead.
    """
    policy = _hook_policy(args)
    if args.json_decision:
        if release:
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse", "permissionDecision": "allow",
                "permissionDecisionReason": release}}))
        else:
            print(decision_json(verdict, change, policy))
        return EXIT_OK

    if release:
        print(release, file=sys.stderr, end="")
        return EXIT_OK

    if args.advisory or not blocks(verdict, policy):
        print(allow_notice(verdict, change, args.advisory), file=sys.stderr, end="")
        for note in verdict.skipped:
            print(f"yieldpoint: not evaluated — {note}", file=sys.stderr)
        return EXIT_OK

    # Exit code 2 is the blocking signal; stderr is fed back to the agent.
    print(render(verdict, change), file=sys.stderr)
    return EXIT_ERROR


def _hook_policy(args) -> Policy:
    """Never allowed to fail the hook: a broken config must not stand between
    a person and their editor. Defaults are the safe fallback."""
    try:
        return Policy.load(args.policy, root=getattr(args, "root", "."))
    except (OSError, ValueError):
        return Policy()


__all__ = ["hook_command"]
