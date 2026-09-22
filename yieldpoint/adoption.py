"""How long this took to earn its place, and whether it kept it.

§10 of the plan named the metric nobody was measuring. Six of the review's nine
items are about not producing *false* blocks; none is about producing a *true*
finding quickly — and the reviewer kept the tool for exactly one reason, stated
plainly: *"the parameter count catch alone justified the round trip."* One true
finding, in the first session.

So: how many runs before the first finding, and what happened to the findings
afterwards. A finding that was fixed is one somebody agreed with. A finding
that was acknowledged is one they did not, and a growing acknowledged share is
the tool being argued with rather than used.

Read entirely from stored timestamps in the ledger. No clock.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Below this there is not enough history to say anything, and a ratio over
#: three findings would be noise dressed as a measurement.
ENOUGH = 10


@dataclass(frozen=True)
class Adoption:
    """What the ledger says about whether this was worth installing."""

    runs: int = 0
    first_run: int = 0
    first_finding_run: int = 0
    """Which run first found something, counting from one. Zero means none has."""

    first_finding_at: int = 0
    findings: int = 0
    acknowledged: int = 0
    fixed: int = 0
    """Distinct file::rule pairs that stopped appearing while the file went on
    being checked — the closest thing to "somebody agreed and acted"."""

    outstanding: int = 0

    @property
    def enough(self) -> bool:
        return self.runs >= ENOUGH

    @property
    def minutes_to_first(self) -> int:
        if not self.first_finding_at or not self.first_run:
            return 0
        return max(0, (self.first_finding_at - self.first_run) // 60)

    @property
    def agreed(self) -> float:
        """The share of resolved findings that were fixed rather than argued with."""
        settled = self.fixed + self.acknowledged
        return self.fixed / settled if settled else 0.0


def _resolve(events) -> tuple[int, int]:
    """Keys that stopped firing while their file kept being checked, and those left.

    A key vanishing because nobody looked at the file again is not a fix. This
    only counts a key gone from a run that did examine its file, which is the
    strongest claim the ledger can support.
    """
    open_keys: dict[str, str] = {}
    fixed = 0
    for event in events:
        checked = set(event.checked)
        for key in list(open_keys):
            path = open_keys[key]
            if path in checked and key not in event.keys:
                del open_keys[key]
                fixed += 1
        for key in event.keys:
            open_keys[key] = key.split("::", 1)[0]
    return fixed, len(open_keys)


def measure(events) -> Adoption:
    """Fold the ledger into the one question a tech lead asks."""
    runs = [e for e in events if e.at]
    if not runs:
        return Adoption()
    first_finding = next(((i, e) for i, e in enumerate(runs, start=1) if e.findings),
                         (0, None))
    fixed, outstanding = _resolve(runs)
    return Adoption(
        runs=len(runs),
        first_run=runs[0].at,
        first_finding_run=first_finding[0],
        first_finding_at=first_finding[1].at if first_finding[1] else 0,
        findings=sum(e.findings for e in runs),
        acknowledged=sum(e.acknowledged for e in runs),
        fixed=fixed,
        outstanding=outstanding,
    )


def render(found: Adoption) -> str:
    if not found.runs:
        return "Nothing recorded yet."
    lines = ["FIRST VALUE — how long this took to earn its place", ""]
    if not found.first_finding_run:
        lines.append(f"  Nothing found in {found.runs:,} run(s). Either this "
                     f"repository is clean or these rules are not the ones it "
                     f"needs — both are worth knowing.")
        return "\n".join(lines)
    minutes = found.minutes_to_first
    when = f", {minutes:,} minute(s) in" if minutes else ""
    lines.append(f"  first finding      run {found.first_finding_run} of "
                 f"{found.runs:,}{when}")
    lines.append(f"  found since        {found.findings:,}")
    lines.append(f"  fixed              {found.fixed:,}  "
                 f"(stopped firing while the file kept being checked)")
    lines.append(f"  acknowledged       {found.acknowledged:,}")
    lines.append(f"  still open         {found.outstanding:,}")
    lines.append("")
    if not found.enough:
        lines.append(f"  Too few runs ({found.runs}) to read a ratio from. The "
                     f"counts above are still real.")
        return "\n".join(lines)
    lines.append(f"  {found.agreed:.0%} of settled findings were fixed rather "
                 f"than acknowledged.")
    lines.append("  A falling share means the tool is being argued with rather "
                 "than used.")
    return "\n".join(lines)


def to_dict(found: Adoption) -> dict:
    return {"runs": found.runs, "first_finding_run": found.first_finding_run,
            "minutes_to_first_finding": found.minutes_to_first,
            "findings": found.findings, "fixed": found.fixed,
            "acknowledged": found.acknowledged, "outstanding": found.outstanding}


def adoption_command(args) -> int:
    from .ledgercommand import run

    return run(args, measure, render, to_dict)


def add_command(sub) -> None:
    from .ledgercommand import register

    register(sub, "adoption",
             "how soon this found something, and what happened next",
             adoption_command)


__all__ = ["Adoption", "measure", "render", "to_dict", "adoption_command",
           "add_command"]
