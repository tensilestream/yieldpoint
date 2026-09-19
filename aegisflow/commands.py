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

from .core.policy import Policy
from .core.verdict import Status, Verdict
from .hook import blocks, decision_json, evaluate, read_payload, render
from .verify import verify_change, verify_diff

EXIT_OK, EXIT_FINDINGS, EXIT_ERROR = 0, 1, 2

#: Nothing in the change could be analysed — no rule ran, so there is no result
#: to trust. Distinct from EXIT_FINDINGS because "I found a problem" and "I
#: cannot tell you anything" are different facts and CI should be able to treat
#: them differently. Only reached when the *whole* change was unanalysable; a
#: change with one Python file among twenty TypeScript ones still exits OK.
EXIT_UNVERIFIED = 3


@dataclass(frozen=True)
class _Run:
    """What a surface knows about a verification that the verdict does not."""

    surface: str
    analysed: int
    elapsed: int
    root: str = "."


def _record(verdict, run: _Run, policy) -> None:
    """Append one ledger line. After the verdict, so it cannot change one."""
    from . import ledger

    if not ledger.enabled(policy):
        return
    ledger.record(
        ledger.observe(
            verdict, run.surface,
            analysed_chars=run.analysed, duration_ms=run.elapsed,
        ),
        ledger.path_for(policy, run.root),
    )


def _exit_for(verdict) -> int:
    if verdict.status is Status.PASS:
        return EXIT_OK
    if verdict.status is Status.UNVERIFIED:
        return EXIT_UNVERIFIED
    return EXIT_FINDINGS

HOOK_MATCHER = "Edit|MultiEdit|Write"


def check(args) -> int:
    if args.diff:
        return check_diff(args)
    if not args.path:
        print("aegisflow: --path is required unless --diff is given", file=sys.stderr)
        return EXIT_ERROR
    try:
        before = _read_source(args.before)
        after = _read_source(args.after)
    except OSError as exc:
        print(f"aegisflow: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if before is None and after is None:
        print("aegisflow: supply --before and/or --after", file=sys.stderr)
        return EXIT_ERROR

    try:
        policy = Policy.load(args.policy)
    except (OSError, ValueError) as exc:
        print(f"aegisflow: {exc}", file=sys.stderr)
        return EXIT_ERROR

    from .ledger import Timer

    if args.speak:
        policy = policy.for_voice()
    with Timer() as timer:
        verdict = verify_change(before, after, args.path, policy)
    _record(verdict, _Run("check", len(before or "") + len(after or ""),
                          timer.elapsed_ms), policy)
    return _emit(verdict, args, policy,
                 deletions=() if after is not None else (args.path,))


def _emit(verdict, args, policy, deletions: tuple = ()) -> int:
    """Print a verdict in whichever form was asked for, and pick the exit code."""
    if getattr(args, "speak", False):
        return _print_spoken(verdict, policy, deletions=deletions)
    if args.json:
        print(verdict.to_json(indent=2))
    else:
        _print_human(verdict, policy)
    return _exit_for(verdict)


def review_command(args) -> int:
    """Verify whatever is not committed yet. The zero-argument entry point.

    Every other command asks what changed. This one asks git, because the person
    running it has already made the change and wants to know what it broke.
    """
    from .verify import verify_diff
    from .worktree import uncommitted

    try:
        policy = Policy.load(args.policy)
    except (OSError, ValueError) as exc:
        print(f"aegisflow: {exc}", file=sys.stderr)
        return EXIT_ERROR

    diff = uncommitted(args.root, staged=args.staged, against=args.against or "")
    if not diff.ok:
        # Nothing to check is not a failure, and neither is "not a git
        # repository" — the other commands still work there.
        print(f"aegisflow: {diff.reason}", file=sys.stderr)
        return EXIT_OK

    from .ledger import Timer

    with Timer() as timer:
        verdict = verify_diff(diff.text, root=diff.root, policy=policy)
    _record(verdict, _Run("review", len(diff.text), timer.elapsed_ms, diff.root), policy)
    return _emit(verdict, args, policy)


def stats_command(args) -> int:
    """Report what the ledger holds. Reads only; records nothing."""
    from . import ledger
    from .stats import render, summarise, to_dict

    try:
        policy = Policy.load(args.policy)
    except (OSError, ValueError) as exc:
        print(f"aegisflow: {exc}", file=sys.stderr)
        return EXIT_ERROR

    path = ledger.path_for(policy, args.root)
    summary = summarise(ledger.load(path))
    if args.json:
        print(json.dumps(to_dict(summary), indent=2))
    else:
        print(render(summary))
        if summary.verdicts:
            print(f"\n  recorded in {path}")
    return EXIT_OK


def check_diff(args) -> int:
    from .verify import verify_diff

    try:
        text = _read_source(args.diff) or ""
        policy = Policy.load(args.policy)
    except (OSError, ValueError) as exc:
        print(f"aegisflow: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if args.speak:
        policy = policy.for_voice()
    verdict = verify_diff(text, root=args.root, policy=policy)
    if args.speak:
        return _print_spoken(verdict, policy)
    if args.json:
        print(verdict.to_json(indent=2))
    else:
        _print_human(verdict, policy)
    return _exit_for(verdict)


def hook_command(args) -> int:
    from .ledger import Timer

    payload = read_payload(sys.stdin.read())
    with Timer() as timer:
        verdict, change = evaluate(payload, args.policy)
    if change.usable:
        _record(
            verdict,
            _Run("hook", len(change.before or "") + len(change.after or ""),
                 timer.elapsed_ms),
            Policy.load(args.policy),
        )

    if args.json_decision:
        print(decision_json(verdict, change))
        return EXIT_OK

    if args.advisory or not blocks(verdict):
        if verdict.findings:
            print(render(verdict, change), file=sys.stderr)
        for note in verdict.skipped:
            print(f"aegisflow: not evaluated — {note}", file=sys.stderr)
        return EXIT_OK

    # Exit code 2 is the blocking signal; stderr is fed back to the agent.
    print(render(verdict, change), file=sys.stderr)
    return EXIT_ERROR


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
    return _exit_for(verdict)


def scan_command(args) -> int:
    from .scan import scan

    try:
        policy = Policy.load(args.policy)
    except (OSError, ValueError) as exc:
        print(f"aegisflow: {exc}", file=sys.stderr)
        return EXIT_ERROR

    result = scan(args.path, policy)
    verdict = result.verdict
    if args.rule:
        wanted = set(args.rule)
        verdict = Verdict.of(
            [f for f in verdict.findings if f.rule in wanted],
            checked=verdict.checked, skipped=verdict.skipped,
        )

    if args.json:
        print(verdict.to_json(indent=2))
        return _exit_for(verdict)

    for note in result.unreadable:
        print(f"unreadable: {note}", file=sys.stderr)

    if not verdict.findings:
        print(f"ok  {result.files} file(s) audited, nothing to report")
        return EXIT_OK

    print(f"{result.files} file(s) audited, {len(verdict.findings)} finding(s)\n")
    for finding in verdict.findings:
        symbol = f" in {finding.symbol}" if finding.symbol else ""
        print(f"  {finding.file}:{finding.line}{symbol}  [{finding.rule}]")
        print(f"    {finding.detail}")

    print("\n  summary")
    counts: dict[str, int] = {}
    for finding in verdict.findings:
        counts[finding.rule] = counts.get(finding.rule, 0) + 1
    for rule, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        print(f"    {count:4}  {rule}")
    print(
        "\n  A scan reports the state of the repository, not the effect of a change. "
        "\n  Rules that are differential when verifying an edit run absolutely here."
    )
    return EXIT_FINDINGS


def linters_command(args) -> int:
    """Show the catalogue, which tools are enabled, and which are installed."""
    import shutil

    from .core.linters import registry
    from .core.linters.adapter import FAST

    try:
        policy = Policy.load(args.policy)
    except (OSError, ValueError):
        policy = Policy()

    enabled = set(policy.linters.tools)
    state = "enabled" if policy.linters.enabled else "disabled"
    print(f"linters: {state}  ({len(enabled)} tool(s) selected)\n")
    print(f"  {'tool':22} {'cost':6} {'installed':10} {'on':4} description")
    for name in registry.names():
        adapter = registry.get(name)
        print(
            f"  {name:22} {'fast' if adapter.cost == FAST else 'slow':6} "
            f"{'yes' if shutil.which(adapter.argv[0]) else 'no':10} "
            f"{'*' if name in enabled else '':4} {adapter.description}"
        )
    print('\nEnable with: "linters": {"enabled": true, "tools": ["ruff"]} in .aegisflow.json')
    print("Linter findings are advisory — they can never block an edit.")
    return EXIT_OK


def _read_source(value: str | None) -> str | None:
    if value is None:
        return None
    if value == "-":
        return sys.stdin.read()
    return Path(value).read_text(encoding="utf-8")


def _print_human(verdict: Verdict, policy: Policy) -> None:
    for warning in policy.warnings:
        print(f"policy warning: {warning}", file=sys.stderr)
    for note in verdict.skipped:
        print(f"skipped: {note}", file=sys.stderr)

    if verdict.status is Status.PASS:
        if verdict.checked:
            print(f"ok  {', '.join(verdict.checked)}")
        elif not verdict.skipped:
            print("ok  nothing to check")
        return

    if verdict.status is Status.UNVERIFIED:
        # Saying "0 findings" here would read as a clean result. Nothing ran.
        print("UNVERIFIED  no rule could analyse this change; see skipped above")
        return

    print(f"{verdict.status.value.upper()}  {len(verdict.findings)} finding(s)\n")
    for finding in verdict.findings:
        symbol = f" in {finding.symbol}" if finding.symbol else ""
        print(f"  {finding.file}:{finding.line}{symbol}  [{finding.rule}]")
        print(f"    {finding.detail}")
        print(f"    fix: {finding.prescription}\n")
