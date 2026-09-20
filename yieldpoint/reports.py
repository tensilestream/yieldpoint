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
    """Check that Yieldpoint is actually doing what it appears to be doing."""
    from . import doctor

    checks = doctor.run(args.root)
    print(doctor.render(checks))
    return EXIT_ERROR if doctor.worst(checks) == doctor.FAIL else EXIT_OK


def report_command(args) -> int:
    """Write a self-contained HTML page from the ledger."""
    from . import ledger, window
    from .htmlreport import Page, render
    from .stats import summarise
    from .timeline import timeline

    try:
        policy = Policy.load(args.policy, root=getattr(args, "root", "."))
        _price(policy, args)
        chosen = window.parse(
            since=args.since or "", run=args.run or "", agent=args.agent or "")
    except (OSError, ValueError, window.BadWindow) as exc:
        print(f"yieldpoint: {exc}", file=sys.stderr)
        return EXIT_ERROR

    path = ledger.path_for(policy, args.root)
    events = window.apply(ledger.load(path), chosen)
    summary = summarise(events, price_per_million=_price(policy, args))
    title, heading = _page_names(policy.project_name)
    page = Page(
        turns=timeline(events),
        price_per_million=_price(policy, args),
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
        print(f"yieldpoint: could not write {target}: {exc}", file=sys.stderr)
        return EXIT_ERROR

    _wrote(target, summary, chosen, policy, path)
    return EXIT_OK


def _wrote(target, summary, chosen, policy, path) -> None:
    """Say what was written, and hand any new events to the configured sink.

    The Stop hook already runs ``report`` every turn, so this is where an export
    belongs: no new wiring, and it cannot run more often than a turn.
    """
    from . import ledger, sink

    sent = sink.flush(policy, ledger.load(path), path)
    print(f"wrote {target}  ({summary.verdicts:,} verification(s), {chosen.describe()})")
    if sent:
        print(f"  exported {sent:,} new event(s) to {sink.configured()[0]}")
    if not summary.verdicts:
        print("  Nothing recorded in that window; the page says so rather than "
              "showing zeros.")


def export_command(args) -> int:
    """Stream the ledger as JSON Lines, or hand it to the configured sink.

    The export path for people who want the numbers somewhere other than this
    machine. Yieldpoint writes to stdout or to a command's stdin and never opens
    a socket; where the bytes go after that is the caller's business.
    """
    from . import ledger, sink, window
    from .contextstats import export_rows

    try:
        policy = Policy.load(args.policy, root=getattr(args, "root", "."))
        chosen = window.parse(
            since=getattr(args, "since", "") or "",
            run=getattr(args, "run", "") or "",
            agent=getattr(args, "agent", "") or "",
        )
    except (OSError, ValueError, window.BadWindow) as exc:
        print(f"yieldpoint: {exc}", file=sys.stderr)
        return EXIT_ERROR

    path = ledger.path_for(policy, args.root)
    events = window.apply(ledger.load(path), chosen)

    if args.sink:
        argv = sink.configured()
        if not argv:
            print(f"yieldpoint: no sink configured; set {sink.ENV_VAR} to a JSON "
                  "array of argv, e.g. '[\"curl\",\"-sS\",\"-XPOST\","
                  "\"--data-binary\",\"@-\",\"https://collector/yp\"]'",
                  file=sys.stderr)
            return EXIT_ERROR
        sent = sink.flush(policy, events, path)
        print(f"sent {sent:,} event(s) to {argv[0]}", file=sys.stderr)
        return EXIT_OK

    for row in export_rows(events):
        print(json.dumps(row, separators=(",", ":")))
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
    "Yieldpoint — Yieldpoint" on this very repository. That sort of detail is
    what makes a tool look unfinished.
    """
    name = (project or "").strip()
    if not name or name.lower() in ("unnamed", "yieldpoint"):
        return "Yieldpoint Verification Report", "Verification Report"
    return f"{name} — Yieldpoint Report", name


def backtest_command(args) -> int:
    """Replay history and report what would have been flagged."""
    from . import backtest

    try:
        policy = Policy.load(args.policy, root=getattr(args, "root", "."))
    except (OSError, ValueError) as exc:
        print(f"yieldpoint: {exc}", file=sys.stderr)
        return EXIT_ERROR

    result = backtest.run(
        args.root, since=args.since, policy=policy, limit=args.limit,
        progress=None if args.json else _tick("replaying"),
    )
    if not args.json:
        print(file=sys.stderr)  # end the progress line
    if result.reason:
        print(f"yieldpoint: {result.reason}", file=sys.stderr)
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
    from .report import to_dict
    from .stats import summarise
    from .timeline import timeline

    try:
        policy = Policy.load(args.policy, root=getattr(args, "root", "."))
    except (OSError, ValueError) as exc:
        print(f"yieldpoint: {exc}", file=sys.stderr)
        return EXIT_ERROR

    path = ledger.path_for(policy, args.root)
    try:
        chosen = window.parse(
            since=getattr(args, "since", "") or "",
            run=getattr(args, "run", "") or "",
            agent=getattr(args, "agent", "") or "",
        )
    except window.BadWindow as exc:
        print(f"yieldpoint: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if getattr(args, "html", None) is not None:
        return _as_page(args)

    events = window.apply(ledger.load(path), chosen)
    try:
        price = _price(policy, args)
        summary = summarise(events, price_per_million=price)
    except ValueError as exc:
        print(f"yieldpoint: {exc}", file=sys.stderr)
        return EXIT_ERROR
    turns = timeline(events)
    if args.json:
        payload = to_dict(summary)
        payload["turns"] = [turn.to_dict() for turn in turns]
        print(json.dumps(payload, indent=2))
    else:
        _stats_text(summary, turns, chosen, path, _price(policy, args))
    return EXIT_OK


def _as_page(args):
    """``stats --html`` is ``report`` with the same window, so it delegates.

    One renderer, not two that drift: whatever the terminal says, the page says.
    """
    from argparse import Namespace

    return report_command(Namespace(
        out=args.html or None,
        root=args.root,
        since=getattr(args, "since", "") or "",
        run=getattr(args, "run", "") or "",
        agent=getattr(args, "agent", "") or "",
        policy=args.policy,
        price=getattr(args, "price", None),
    ))


def _price(policy, args) -> float:
    """``--price`` for one run, otherwise whatever the project configured."""
    import math
    chosen = getattr(args, "price", None)
    value = policy.metrics.price_per_million if chosen is None else chosen
    if not math.isfinite(value) or value < 0:
        raise ValueError("price must be finite and non-negative")
    return value


def _stats_text(summary, turns, chosen, path, price: float) -> None:
    """The totals, then the timeline, then where the numbers came from."""
    from .report import render
    from .timeline import render as render_turns

    print(render(summary))
    from .contextstats import render as render_context
    print("\n" + render_context(summary.context))
    per_turn = render_turns(turns, price_per_million=price)
    if per_turn:
        print()
        print(per_turn)
    print(f"\n  {chosen.describe()}, from {path}")
    if not summary.verdicts and not chosen.everything:
        print("  Nothing in that window. `yieldpoint stats` shows everything.")


__all__ = [
    "doctor_command", "backtest_command", "stats_command", "report_command",
    "export_command",
]
