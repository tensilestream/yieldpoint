"""Commands that answer "what happened?" rather than verify a change.

Split from commands.py because they are read for different reasons and change
at different times: that file is the verification surface, this one is how a
person finds out whether any of it is working and what it has done.
"""

from __future__ import annotations

import json
import sys

from pathlib import Path

from .core.policy import Policy

EXIT_OK, EXIT_ERROR = 0, 2


def doctor_command(args) -> int:
    """Check that AegisFlow is actually doing what it appears to be doing."""
    from . import doctor

    checks = doctor.run(args.root)
    print(doctor.render(checks))
    return EXIT_ERROR if doctor.worst(checks) == doctor.FAIL else EXIT_OK


def report_command(args) -> int:
    """Write a self-contained HTML page from the ledger."""
    from . import ledger, window
    from .htmlreport import Page, render
    from .stats import summarise

    try:
        policy = Policy.load(args.policy)
        chosen = window.parse(
            since=args.since or "", run=args.run or "", agent=args.agent or "")
    except (OSError, ValueError, window.BadWindow) as exc:
        print(f"aegisflow: {exc}", file=sys.stderr)
        return EXIT_ERROR

    path = ledger.path_for(policy, args.root)
    summary = summarise(window.apply(ledger.load(path), chosen))
    title, heading = _page_names(policy.project_name)
    page = Page(
        now=_current(args.root, policy),
        title=title,
        heading=heading,
        summary=summary,
        scope=chosen.describe(),
        source=str(path),
    )

    # Inside the state directory by default: one file, refreshed in place.
    # Writing a new page per run would accumulate untracked files in somebody's
    # repository, and writing to the root would put one there at all.
    target = Path(args.out) if args.out else (
        ledger.path_for(policy, args.root).parent / "report.html")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render(page), encoding="utf-8")
    except OSError as exc:
        print(f"aegisflow: could not write {target}: {exc}", file=sys.stderr)
        return EXIT_ERROR

    print(f"wrote {target}  ({summary.verdicts:,} verification(s), {chosen.describe()})")
    if not summary.verdicts:
        print("  Nothing recorded in that window; the page says so rather than "
              "showing zeros.")
    return EXIT_OK


def _current(root, policy):
    """What the working tree needs right now.

    The history in the ledger says what has been caught; this says what is
    outstanding. A report that only totals the past cannot answer the question
    someone opened it to ask.
    """
    from .htmlreport import Now
    from .verify import verify_diff
    from .worktree import uncommitted

    from .harness.pacing import pace

    diff = uncommitted(root)
    if not diff.ok:
        return Now(reason=diff.reason)
    verdict = verify_diff(diff.text, diff.root, policy)
    added = sum(1 for line in diff.text.splitlines()
                if line.startswith("+") and not line.startswith("+++"))
    files = len({line.split()[-1] for line in diff.text.splitlines()
                 if line.startswith("+++")})
    return Now(
        findings=tuple(verdict.findings),
        checked=len(verdict.checked),
        pace=pace(verdict, added, files, policy.structure.max_change_lines),
    )


def _page_names(project: str) -> tuple[str, str]:
    """``(tab title, page heading)``.

    Two names because they sit in different places. The tab and the gallery
    need the product name to be findable; the masthead already prints it in the
    eyebrow directly above the heading, so repeating it there gives
    "AegisFlow — AegisFlow" on this very repository. That sort of detail is
    what makes a tool look unfinished.
    """
    name = (project or "").strip()
    if not name or name.lower() in ("unnamed", "aegisflow"):
        return "AegisFlow Verification Report", "Verification Report"
    return f"{name} — AegisFlow Report", name


def backtest_command(args) -> int:
    """Replay history and report what would have been flagged."""
    from . import backtest

    try:
        policy = Policy.load(args.policy)
    except (OSError, ValueError) as exc:
        print(f"aegisflow: {exc}", file=sys.stderr)
        return EXIT_ERROR

    result = backtest.run(
        args.root, since=args.since, policy=policy, limit=args.limit,
        progress=None if args.json else _tick("replaying"),
    )
    if not args.json:
        print(file=sys.stderr)  # end the progress line
    if result.reason:
        print(f"aegisflow: {result.reason}", file=sys.stderr)
        return EXIT_ERROR

    if args.json:
        print(json.dumps({
            "commits": len(result.commits),
            "flagged": len(result.flagged),
            "contract_flagged": len(result.contract_flagged),
            "contract_rate": round(result.contract_rate, 3),
            "by_rule": result.by_rule(),
            "details": [
                {"sha": c.sha, "subject": c.subject, "rules": list(c.rules)}
                for c in result.flagged
            ],
        }, indent=2))
    else:
        print(backtest.render(result, args.since))
    return EXIT_OK


def _tick(label: str):
    """A progress line on stderr. Never stdout, which carries results."""
    def report(done: int, total: int, detail: str) -> None:
        width = 28
        filled = int(width * done / total) if total else width
        bar = "#" * filled + "." * (width - filled)
        print(f"\r  {label} [{bar}] {done}/{total}  {detail:<12}",
              end="", file=sys.stderr, flush=True)
    return report


def stats_command(args) -> int:
    """Report what the ledger holds. Reads only; records nothing."""
    from . import ledger, window
    from .report import render, to_dict
    from .stats import summarise

    try:
        policy = Policy.load(args.policy)
    except (OSError, ValueError) as exc:
        print(f"aegisflow: {exc}", file=sys.stderr)
        return EXIT_ERROR

    path = ledger.path_for(policy, args.root)
    try:
        chosen = window.parse(
            since=getattr(args, "since", "") or "",
            run=getattr(args, "run", "") or "",
            agent=getattr(args, "agent", "") or "",
        )
    except window.BadWindow as exc:
        print(f"aegisflow: {exc}", file=sys.stderr)
        return EXIT_ERROR

    events = window.apply(ledger.load(path), chosen)
    summary = summarise(events)
    if args.json:
        print(json.dumps(to_dict(summary), indent=2))
    else:
        print(render(summary))
        print(f"\n  {chosen.describe()}, from {path}")
        if not summary.verdicts and not chosen.everything:
            print("  Nothing in that window. `aegisflow stats` shows everything.")
    return EXIT_OK


__all__ = [
    "doctor_command", "backtest_command", "stats_command", "report_command",
]
