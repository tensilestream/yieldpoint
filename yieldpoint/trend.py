"""What this has found, week by week.

Review item #8, and the reason it matters is not the chart: *"that's the
difference between installed and kept."* An individual installs a tool; the
person who decides it stays is usually someone else, looking at it
occasionally, asking whether it is earning its place.

Totals cannot answer that. "245 findings" says nothing about whether the
repository is getting better. The split does: debt this change *introduced*
against debt it *inherited*, over time. Introduced going down is a team
learning. Inherited going down is a team paying off. Both flat is a tool being
ignored, and a tech lead deserves to see that too.

Every date here comes from a stored timestamp. Nothing reads the current clock,
so the same ledger renders identically tomorrow (RULES.md section 4).
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

#: Weekly. Daily is noise on a repository with a normal commit rhythm, and
#: monthly hides a regression for three weeks.
DAYS = 7


@dataclass(frozen=True)
class Period:
    """One week of verification, as counts."""

    starting: str
    turns: int = 0
    found: int = 0
    introduced: int = 0
    inherited: int = 0
    acknowledged: int = 0
    unclassified: int = 0
    """Findings from turns recorded before attribution existed. Their split is
    not unknown-but-zero, it is unknown, and adding them to either column would
    be inventing history."""

    @property
    def clean(self) -> bool:
        return not self.found


def _week(at: int) -> str:
    """The Monday of the week containing this stored timestamp."""
    day = datetime.datetime.fromtimestamp(at, datetime.timezone.utc).date()
    return (day - datetime.timedelta(days=day.weekday())).isoformat()


def periods(events) -> list[Period]:
    """One row per week that has any verification in it, oldest first."""
    buckets: dict[str, dict] = {}
    for event in events:
        if not event.at:
            continue
        row = buckets.setdefault(_week(event.at), {
            "turns": 0, "found": 0, "introduced": 0, "inherited": 0,
            "acknowledged": 0, "unclassified": 0})
        row["turns"] += 1
        row["found"] += event.findings
        row["acknowledged"] += event.acknowledged
        if event.inherited is None:
            row["unclassified"] += event.findings
        else:
            row["inherited"] += event.inherited
            row["introduced"] += event.findings - event.inherited
    return [Period(starting=week, **row) for week, row in sorted(buckets.items())]


def _direction(rows: list[Period]) -> str:
    """Whether introduced debt is falling, over weeks that could be classified."""
    known = [r for r in rows if not r.unclassified and r.turns]
    if len(known) < 2:
        return ("Not enough classified history yet to say which way this is "
                "going. Two full weeks will do it.")
    first, last = known[0].introduced, known[-1].introduced
    if first == last:
        return f"Findings introduced per week are flat at {first}."
    way = "down" if last < first else "up"
    return (f"Findings introduced per week has gone {way}, {first} to {last}, "
            f"across {len(known)} classified week(s).")


def render(rows: list[Period]) -> str:
    if not rows:
        return "Nothing recorded yet. Run a verification and this fills in."
    lines = ["TREND — what this has found, week by week", "",
             f"  {'week starting':<14} {'turns':>6} {'found':>6} "
             f"{'introduced':>11} {'inherited':>10} {'acknowledged':>13}"]
    unsplit = 0
    for row in rows:
        unsplit += row.unclassified
        shown = "—" if row.unclassified else f"{row.introduced:>11}"
        inherited = "—" if row.unclassified else f"{row.inherited:>10}"
        lines.append(f"  {row.starting:<14} {row.turns:>6} {row.found:>6} "
                     f"{shown:>11} {inherited:>10} {row.acknowledged:>13}")
    lines.append("")
    lines.append(f"  {_direction(rows)}")
    if unsplit:
        lines.append(f"  {unsplit:,} finding(s) predate attribution and have no "
                     f"split recorded — shown as —, never folded into either column.")
    lines.append("  Introduced is what a change wrote. Inherited is debt it "
                 "added to but did not create.")
    return "\n".join(lines)


def to_dict(rows: list[Period]) -> dict:
    return {"weeks": [{
        "starting": r.starting, "turns": r.turns, "found": r.found,
        "introduced": r.introduced, "inherited": r.inherited,
        "acknowledged": r.acknowledged, "unclassified": r.unclassified}
        for r in rows]}


def trend_command(args) -> int:
    from .ledgercommand import run

    return run(args, periods, render, to_dict)


def add_command(sub) -> None:
    from .ledgercommand import register

    register(sub, "trend",
             "what this has found over time, introduced against inherited",
             trend_command)


__all__ = ["Period", "periods", "render", "to_dict", "trend_command", "add_command"]
