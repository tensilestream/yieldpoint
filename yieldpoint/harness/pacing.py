"""When to stop and commit.

``change_too_large`` is a true finding and an unhelpful one: by the time it
fires the work is done, and "split this into reviewable pieces" means unpicking
four thousand lines after the fact. An agent working for hours needs the same
judgement one turn at a time — *is this a good place to stop?* — while stopping
is still cheap.

That question is answerable from what is already measured: how much has changed
since the last commit, and whether what is there now is sound.

**Everything here is a warning, never a stop.** Nothing in this module denies an
edit, fails a command, or changes an exit code. That is deliberate: this cannot
tell whether the work is *finished*, and interrupting an agent halfway through a
function to enforce a line budget leaves the repository in a worse state than
letting it finish. The size limit is about what a human can review, and
half-written code is not reviewable at any length.

So the advice is always phrased against the **next natural boundary**: finish
what you are on, then commit before starting anything new. The urgency grows
with the overrun; the instruction does not change.

Two inputs, and the order matters. **Correctness first**: a change that weakened
the suite is worth attention now rather than at the next boundary, because
every further turn is built on top of it. **Then size**, which can always wait
for the current piece to be done.

What this does not know is whether the work is finished. It can say the change
is large enough, and sound enough, that the next stopping point should be a
commit. Whether the feature works stays the agent's judgement, and this is one
input to it.
"""

from __future__ import annotations

from .decisions import Choice

PACE = ("continue", "wrap-up", "overdue", "fix-first")
"""``wrap-up`` and ``overdue`` differ only in urgency: both mean "finish the
current piece, then commit before starting anything new". Neither means stop
where you are."""

#: Fraction of the change budget at which landing beats continuing. Below this
#: the overhead of a commit outweighs the risk of growing too large; above it
#: the reverse, and the margin leaves room for the turn in progress.
COMMIT_AT = 0.6

#: Rules that mean the suite lost verification strength. A change carrying one
#: of these is not a candidate for committing at any size.
CONTRACT_RULES = frozenset({
    "assertion_monotonicity", "vacuous_assertion", "empty_test",
    "skip_marker", "disabled_assertion", "dangling_reference",
    "export_removed", "boundary_violation",
})


def pace(verdict, added_lines: int, files: int, limit: int) -> Choice:
    """What to do at the next stopping point, and why.

    Never an instruction to stop where you are — see the module docstring.
    """
    broken = sorted({f.rule for f in verdict.findings if f.rule in CONTRACT_RULES})
    used = (added_lines / limit) if limit else 0.0
    value, reason = _decide(broken, used, added_lines, files, limit)
    return Choice(
        question="pace",
        value=value,
        options=PACE,
        reason=reason,
        signals={
            "added_lines": added_lines,
            "files": files,
            "limit": limit,
            "budget_used": round(used, 3),
            "correctness_findings": broken,
        },
    )


def _decide(broken, used: float, added: int, files: int,
            limit: int) -> tuple[str, str]:
    if broken:
        return "fix-first", (
            f"{', '.join(broken)} — worth fixing before the next turn builds "
            "on top of it, rather than at the next commit"
        )
    if not limit:
        return "continue", "no change limit configured"
    if used >= 1:
        return "overdue", (
            f"{added:,} lines across {files} file(s) is {used:.1f}x the "
            f"reviewable limit of {limit:,}. Finish what you are on, then "
            "commit — and start nothing new until you have"
        )
    if used >= COMMIT_AT:
        return "wrap-up", (
            f"{added:,} of {limit:,} lines used ({used:.0%}). Finish the "
            "current piece, then commit before starting anything new"
        )
    return "continue", (
        f"{added:,} of {limit:,} lines used ({used:.0%}); room to keep going"
    )


def bar(decision: Choice, width: int = 24) -> str:
    """A one-line budget gauge for a terminal."""
    used = float(decision.signals.get("budget_used") or 0)
    filled = min(width, round(width * used))
    over = used > 1
    return (
        f"[{'#' * filled}{'.' * (width - filled)}] "
        f"{decision.signals.get('added_lines', 0):,}/"
        f"{decision.signals.get('limit', 0):,} lines"
        f"{'  OVER' if over else ''}"
    )


__all__ = ["pace", "bar", "PACE", "COMMIT_AT", "CONTRACT_RULES"]
