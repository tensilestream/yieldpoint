"""Command implementations.

Separated from cli.py so that the argument surface and the work are independent:
adding a flag touches one file, changing what a command does touches the other.
Each handler returns a process exit code and prints its own output, because the
shell contract — 0 clean, 1 findings, 2 error — is part of the CLI's API.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .core.policy import Policy
from .core.verdict import Status, Verdict
from .hook import blocks, decision_json, evaluate, read_payload, render
from .verify import verify_change, verify_diff

EXIT_OK, EXIT_FINDINGS, EXIT_ERROR = 0, 1, 2

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

    if args.speak:
        policy = policy.for_voice()
    verdict = verify_change(before, after, args.path, policy)
    if args.speak:
        return _print_spoken(verdict, policy, deletions=() if after is not None else (args.path,))
    if args.json:
        print(verdict.to_json(indent=2))
    else:
        _print_human(verdict, policy)
    return EXIT_OK if verdict.status is Status.PASS else EXIT_FINDINGS


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
    return EXIT_OK if verdict.status is Status.PASS else EXIT_FINDINGS


def hook_command(args) -> int:
    payload = read_payload(sys.stdin.read())
    verdict, change = evaluate(payload, args.policy)

    if args.json_decision:
        print(decision_json(verdict, change))
        return EXIT_OK

    if verdict.status is Status.PASS or args.advisory:
        if verdict.findings:
            print(render(verdict, change), file=sys.stderr)
        return EXIT_OK

    if blocks(verdict):
        # Exit code 2 is the blocking signal; stderr is fed back to the agent.
        print(render(verdict, change), file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK


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
    return EXIT_OK if verdict.status is Status.PASS else EXIT_FINDINGS


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
        return EXIT_OK if verdict.status is Status.PASS else EXIT_FINDINGS

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

    print(f"{verdict.status.value.upper()}  {len(verdict.findings)} finding(s)\n")
    for finding in verdict.findings:
        symbol = f" in {finding.symbol}" if finding.symbol else ""
        print(f"  {finding.file}:{finding.line}{symbol}  [{finding.rule}]")
        print(f"    {finding.detail}")
        print(f"    fix: {finding.prescription}\n")
