"""Rendering for a pre-edit brief.

Separate from brief.py because the two change for different reasons: that one
when there is a new fact worth knowing, this one when there is a better way to
say it.

Written to be read by a model as much as by a person, which means short. A
briefing long enough to push the task out of context has cost more than the
mistake it prevents.
"""

from __future__ import annotations

from .brief import Brief, FileBrief

MAX_ASSERTIONS_SHOWN = 8
MAX_REPEATS_SHOWN = 3


def _history(entry: FileBrief) -> list[str]:
    """What has already gone wrong here, and what nothing has looked at.

    A path with no recorded finding is not a safe path — it may simply never
    have been analysed. Those two states read identically unless one of them
    says so (RULES.md section 5).
    """
    out = []
    if entry.repeats:
        worst = ", ".join(f"{rule} x{count}"
                          for rule, count in entry.repeats[:MAX_REPEATS_SHOWN])
        out.append(f"    has tripped before: {worst} — expect the same again")
    if entry.unchecked:
        out.append("    changed since anything last analysed it")
    elif entry.never_checked and entry.exists:
        out.append("    never analysed — no findings here means nobody looked, "
                   "not that it is clean")
    return out


def _crowding(entry: FileBrief) -> list[str]:
    """What is already full, loudest first."""
    out = [
        f"    ALREADY OVER: {item.name} has {item.used} {item.measure}, "
        f"limit {item.limit} — do not add to it"
        for item in entry.crowded if item.over
    ]
    out.extend(
        f"    near the limit: {item.name} {item.measure} {item.used}/{item.limit}"
        for item in [c for c in entry.crowded if not c.over][:4]
    )
    return out


def _protected(entry: FileBrief) -> list[str]:
    """The assertions, verbatim. A count alone still leaves a guess."""
    if not entry.protected:
        return []
    out = [f"    protected test file — {len(entry.assertions)} assertion(s) "
           "must not get weaker:"]
    out.extend(f"      {raw[:88]}" for raw in entry.assertions[:MAX_ASSERTIONS_SHOWN])
    remaining = len(entry.assertions) - MAX_ASSERTIONS_SHOWN
    if remaining > 0:
        out.append(f"      ... and {remaining} more")
    return out


def _file_lines(entry: FileBrief) -> list[str]:
    out = [f"  {entry.path}" + ("  (new file)" if not entry.exists else "")]
    if entry.unreadable:
        # Not a short circuit: what the ledger already knows about this path is
        # still true, and is the most useful thing to say about a file nothing
        # can measure.
        out.append(f"    {entry.unreadable[:70]}")
        return out + _history(entry)
    if entry.line_limit:
        out.append(f"    room: {entry.headroom} more lines of code "
                   f"({entry.lines}/{entry.line_limit})")
    out.extend(_history(entry))
    out.extend(_crowding(entry))
    if entry.forbidden_imports:
        out.append(f"    zone `{entry.zone}` may not import: "
                   f"{', '.join(entry.forbidden_imports)}")
    out.extend(_protected(entry))
    return out


def render(report: Brief) -> str:
    """The briefing, or a single line saying there is nothing to say."""
    if not report.files:
        return "No files named, so nothing to brief on."
    if not report.anything_to_say:
        return ("Nothing to watch in these files: no protected assertions, no "
                "crowded functions, no zone restrictions.")

    lines = ["Before you edit, in this project:"]
    for entry in report.files:
        lines.extend(_file_lines(entry))
    lines.append("")
    lines.append(f"  whole change: keep under {report.change_budget:,} added lines")
    lines.append("  Everything above was read from the files. Nothing here is a "
                 "prediction.")
    return "\n".join(lines)


def to_dict(report: Brief) -> dict:
    return {
        "project": report.project,
        "change_budget_lines": report.change_budget,
        "files": [
            {
                "path": f.path,
                "exists": f.exists,
                "lines": f.lines,
                "line_limit": f.line_limit,
                "headroom": f.headroom,
                "protected": f.protected,
                "assertions_that_must_not_weaken": list(f.assertions),
                "crowded": [
                    {"symbol": c.name, "measure": c.measure,
                     "used": c.used, "limit": c.limit, "over": c.over}
                    for c in f.crowded
                ],
                "zone": f.zone,
                "forbidden_imports": list(f.forbidden_imports),
                "unreadable": f.unreadable,
                "rules_that_fired_here_before": [
                    {"rule": rule, "times": times} for rule, times in f.repeats],
                "changed_since_last_analysed": f.unchecked,
                "never_analysed": f.never_checked,
            }
            for f in report.files
        ],
    }


def brief_command(args) -> int:
    """Say what is true about these files before anything is edited.

    The cheapest verdict is the one that never has to be issued. Everything
    here is read off the syntax tree and the ledger — no model call, no network.

    Lives here rather than in commands.py for the same reason ``compact_command``
    lives with compaction: a command and the thing it presents change together.
    """
    import json
    import sys

    from .brief import brief
    from .core.policy import Policy

    try:
        policy = Policy.load(args.policy, root=getattr(args, "root", "."))
    except (OSError, ValueError) as exc:
        print(f"yieldpoint: {exc}", file=sys.stderr)
        return 2

    report = brief(args.paths, policy, args.root)
    print(json.dumps(to_dict(report), indent=2) if args.json else render(report))
    return 0


__all__ = ["render", "to_dict", "brief_command"]
