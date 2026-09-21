"""Command implementations.

Separated from cli.py so that the argument surface and the work are independent:
adding a flag touches one file, changing what a command does touches the other.
Each handler returns a process exit code and prints its own output, because the
shell contract — 0 clean, 1 findings, 2 error — is part of the CLI's API.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from . import console
from .core.policy import Policy
from .ledger import Run, record_run as _record
from .core.verdict import Status, Verdict
from .hook import blocks, decision_json, evaluate, read_payload, render
from .verify import verify_change, verify_diff

EXIT_OK, EXIT_FINDINGS, EXIT_ERROR = 0, 1, 2

from .audit import linters_command, scan_command  # noqa: E402,F401

#: Nothing in the change could be analysed — no rule ran, so there is no result
#: to trust. Distinct from EXIT_FINDINGS because "I found a problem" and "I
#: cannot tell you anything" are different facts and CI should be able to treat
#: them differently. Only reached when the *whole* change was unanalysable; a
#: change with one Python file among twenty TypeScript ones still exits OK.
EXIT_UNVERIFIED = 3


def only_maintainability(verdict, policy) -> bool:
    """True when everything found describes shape rather than a weakening.

    These are worth showing and not worth stopping for. A commit refused
    because a function is fifty-one lines teaches people to reach for
    ``--no-verify``, and the habit does not distinguish that finding from the
    one that says an assertion is gone.
    """
    from .core.policychange import POLICY_WEAKENED
    from .core.structure import MAINTAINABILITY_RULES

    if not verdict.findings:
        return False
    rules = {f.rule for f in verdict.findings}
    # A loosened policy is reported and never enforced, whatever `gates` says.
    # Denying the edit that relaxes a rule would leave a project unable to
    # change its own standards without first defeating the tool enforcing them.
    if policy.structure.gates:
        return rules <= {POLICY_WEAKENED}
    return rules <= MAINTAINABILITY_RULES | {POLICY_WEAKENED}


def _exit_for(verdict, policy=None) -> int:
    if verdict.status is Status.PASS:
        return EXIT_OK
    if verdict.status is Status.UNVERIFIED:
        return EXIT_UNVERIFIED
    if policy is not None and only_maintainability(verdict, policy):
        return EXIT_OK
    return EXIT_FINDINGS

HOOK_MATCHER = "Edit|MultiEdit|Write"


def check(args) -> int:
    if args.diff:
        return check_diff(args)
    if not args.path:
        print("yieldpoint: --path is required unless --diff is given", file=sys.stderr)
        return EXIT_ERROR
    try:
        before = _read_source(args.before)
        after = _read_source(args.after)
    except OSError as exc:
        print(f"yieldpoint: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if before is None and after is None:
        print("yieldpoint: supply --before and/or --after", file=sys.stderr)
        return EXIT_ERROR

    try:
        policy = Policy.load(args.policy, root=getattr(args, "root", "."))
    except (OSError, ValueError) as exc:
        print(f"yieldpoint: {exc}", file=sys.stderr)
        return EXIT_ERROR

    from .ledger import Timer

    if args.speak:
        policy = policy.for_voice()
    with Timer() as timer:
        verdict = verify_change(before, after, args.path, policy)
    _record(verdict, Run("check", len(before or "") + len(after or ""),
                          timer.elapsed_ms, args.root), policy)
    return _emit(verdict, args, policy,
                 deletions=() if after is not None else (args.path,))


def _emit(verdict, args, policy, deletions: tuple = ()) -> int:
    """Print a verdict in whichever form was asked for, and pick the exit code."""
    if getattr(args, "speak", False):
        return _print_spoken(verdict, policy, deletions=deletions)
    if getattr(args, "sarif", False):
        from . import sarif

        print(sarif.dumps(verdict, advisory=sarif.advisory_rules(policy)))
        return _exit_for(verdict, policy)
    if args.json:
        print(verdict.to_json(indent=2))
    else:
        console.print_human(verdict, policy,
                            staged=getattr(args, "staged", False),
                            root=getattr(args, "root", "."))
    return _exit_for(verdict, policy)


def _use_cache_for(root) -> None:
    """Store analysis beside the repository, not beside the shell's cwd."""
    from .core.locate import repository
    from .core.parsecache import configure

    configure(repository(root))


def review_command(args) -> int:
    """Verify whatever is not committed yet. The zero-argument entry point.

    Every other command asks what changed. This one asks git, because the person
    running it has already made the change and wants to know what it broke.
    """
    from .verify import verify_diff
    from .worktree import uncommitted

    try:
        policy = Policy.load(args.policy, root=getattr(args, "root", "."))
    except (OSError, ValueError) as exc:
        print(f"yieldpoint: {exc}", file=sys.stderr)
        return EXIT_ERROR

    from .basis import resolve

    _use_cache_for(args.root)
    # Resolved before the diff, because the answer changes what "worse" means:
    # against a branch base, every commit on this branch is this change's.
    basis = resolve(args.root, args.against or "")
    diff = uncommitted(args.root, staged=args.staged, against=basis.revision)
    if not diff.ok:
        # Nothing to check is not a failure, and neither is "not a git
        # repository" — the other commands still work there.
        print(f"yieldpoint: {diff.reason}", file=sys.stderr)
        return EXIT_OK

    from .ledger import Timer

    with Timer() as timer:
        verdict = verify_diff(diff.text, root=diff.root, policy=policy)
    _record(verdict, Run("review", len(diff.text), timer.elapsed_ms, diff.root), policy)
    code = _emit(verdict, args, policy)
    if not _machine_readable(args):
        print(f"  {basis.describe()}")
        console.print_pace(verdict, diff, policy)
    return code


def _machine_readable(args) -> bool:
    """Whether stdout is being parsed rather than read.

    Anything printed beside the payload corrupts it, so every human-facing
    extra — the comparison basis, the pacing bar — has to ask first.
    """
    return bool(getattr(args, "json", False) or getattr(args, "sarif", False))


def check_diff(args) -> int:
    from .verify import verify_diff

    try:
        text = _read_source(args.diff) or ""
        policy = Policy.load(args.policy, root=getattr(args, "root", "."))
    except (OSError, ValueError) as exc:
        print(f"yieldpoint: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if args.speak:
        policy = policy.for_voice()
    from .ledger import Timer
    with Timer() as timer:
        verdict = verify_diff(text, root=args.root, policy=policy)
    _record(verdict, Run("check:diff", len(text), timer.elapsed_ms, args.root), policy)
    if args.speak:
        return _print_spoken(verdict, policy)
    if args.json:
        print(verdict.to_json(indent=2))
    else:
        console.print_human(verdict, policy,
                            staged=getattr(args, "staged", False),
                            root=getattr(args, "root", "."))
    return _exit_for(verdict, policy)


def _handoff(args) -> int | None:
    """Other hook events share this entry point; ``None`` means PreToolUse."""
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

    from .ledger import Timer

    payload = read_payload(sys.stdin.read())
    with Timer() as timer:
        verdict, change = evaluate(payload, args.policy)

    # Loaded once, and never allowed to fail the hook: a broken config must not
    # stand between a person and their editor. Defaults are the safe fallback.
    try:
        policy = Policy.load(args.policy, root=getattr(args, "root", "."))
    except (OSError, ValueError):
        policy = Policy()

    if change.usable:
        _record(
            verdict,
            Run("hook", len(change.before or "") + len(change.after or ""),
                 timer.elapsed_ms),
            policy,
        )

    if args.json_decision:
        print(decision_json(verdict, change, policy))
        return EXIT_OK

    if args.advisory or not blocks(verdict, policy):
        print(_allow_notice(verdict, change, args.advisory), file=sys.stderr, end="")
        for note in verdict.skipped:
            print(f"yieldpoint: not evaluated — {note}", file=sys.stderr)
        return EXIT_OK

    # Exit code 2 is the blocking signal; stderr is fed back to the agent.
    print(render(verdict, change), file=sys.stderr)
    return EXIT_ERROR


def stop_command(args) -> int:
    """Verify the whole working tree when the agent stops.

    The per-edit hook cannot see a change made through the shell; this can,
    because it asks git rather than the tool call. Always exits 0 — a Stop hook
    signals through its JSON, and a non-zero exit here would read as the hook
    itself being broken.
    """
    from . import stop
    from .ledger import Timer

    payload = read_payload(sys.stdin.read())
    with Timer() as timer:
        outcome = stop.evaluate(args.root, args.policy)

    if outcome.ran:
        _record(
            outcome.verdict,
            Run("stop", outcome.analysed, timer.elapsed_ms, outcome.root),
            Policy.load(args.policy, root=getattr(args, "root", ".")),
        )

    response = stop.decision(
        outcome, advisory=args.advisory, looped=stop.suppressed(payload)
    )
    if response:
        print(json.dumps(response))
    elif outcome.reason:
        # Not a finding and not silence: say why nothing was checked, on stderr
        # so it cannot be mistaken for the hook's JSON response.
        print(f"yieldpoint: {outcome.reason}", file=sys.stderr)
    return EXIT_OK


def _allow_notice(verdict, change, advisory: bool) -> str:
    """What to say on an edit that was permitted.

    In advisory mode the full report is right — nothing is being enforced, so
    the point is to show what would have been. Otherwise only the deferred
    findings are worth mentioning, because the rest were genuinely fine.
    """
    from .hook import render_deferred

    if advisory and verdict.findings:
        return render(verdict, change) + "\n"
    note = render_deferred(verdict)
    return note + "\n" if note else ""


def _print_spoken(verdict: Verdict, policy: Policy, deletions: tuple = ()) -> int:
    from .speech import speak

    utterance = speak(
        verdict,
        deletions=deletions,
        max_details=policy.voice.max_spoken_findings,
        confirm_threshold=policy.voice.confirm_on_removals,
    )
    print(utterance.summary)
    for detail in utterance.details:
        print(f"  {detail}")
    if utterance.confirmation:
        print(f"\n  {utterance.confirmation.question}")
    return _exit_for(verdict, policy)


def _read_source(value: str | None) -> str | None:
    if value is None:
        return None
    if value == "-":
        return sys.stdin.read()
    return Path(value).read_text(encoding="utf-8")


