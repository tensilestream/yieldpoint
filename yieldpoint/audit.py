"""Commands that report on a repository rather than on a change.

Split from commands.py because the two answer different questions. That file
is "what did this edit do"; this one is "what is here". They also change for
different reasons — a new rule touches neither, a new output format touches
one — and keeping them together had put commands.py over the length limit it
enforces on everyone else.
"""

from __future__ import annotations

import sys

from .core.policy import Policy
from .core.verdict import Verdict

EXIT_OK, EXIT_FINDINGS, EXIT_ERROR = 0, 1, 2


def scan_command(args) -> int:
    # Imported here, not at module scope: commands.py re-exports these two, so
    # a module-level import back into it would close an import cycle.
    from .commands import _exit_for
    from .scan import scan

    try:
        policy = Policy.load(args.policy, root=getattr(args, "root", "."))
    except (OSError, ValueError) as exc:
        print(f"yieldpoint: {exc}", file=sys.stderr)
        return EXIT_ERROR

    result = scan(args.path, policy)
    verdict = _only(result.verdict, args.rule)

    if args.json:
        print(verdict.to_json(indent=2))
        return _exit_for(verdict, policy)

    return _report(result, verdict)


def _only(verdict, rules) -> "Verdict":
    """The findings for the rules asked for, keeping what was and was not read."""
    if not rules:
        return verdict
    wanted = set(rules)
    return Verdict.of([f for f in verdict.findings if f.rule in wanted],
                      checked=verdict.checked, skipped=verdict.skipped)


def _summary(findings) -> list[str]:
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.rule] = counts.get(finding.rule, 0) + 1
    return [f"    {count:4}  {rule}" for rule, count
            in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]


def _report(result, verdict) -> int:
    """The human rendering of an audit, and the exit code that goes with it."""
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
    print("\n".join(_summary(verdict.findings)))
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
        policy = Policy.load(args.policy, root=getattr(args, "root", "."))
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
    print('\nEnable with: "linters": {"enabled": true, "tools": ["ruff"]} in .yieldpoint.json')
    print("Linter findings are advisory — they can never block an edit.")
    return EXIT_OK


__all__ = ["scan_command", "linters_command"]
