"""Putting a verdict on a terminal.

Split from commands.py because the two change for different reasons: that file
is what each command does, this is what a person sees. It also keeps both under
the length limit this project enforces on everyone else.

Colour is applied through branding.palette, which returns empty strings when
stdout is not a terminal — so there is never a conditional around a print, and
a piped run is byte-identical to an uncoloured one.
"""

from __future__ import annotations

import sys

from .core.policy import Policy
from .core.verdict import Status, Verdict

#: Rules that mean the suite lost strength. Coloured apart from the rest,
#: because "a function is long" and "an assertion no longer holds" should not
#: look the same at a glance.
_CONTRACT = frozenset({
    "assertion_monotonicity", "vacuous_assertion", "empty_test",
    "skip_marker", "disabled_assertion", "dangling_reference",
    "export_removed", "boundary_violation",
})



def print_pace(verdict, diff, policy: Policy) -> None:
    """Say whether this is a good place to stop.

    Printed after the findings because it answers a different question: not
    "what is wrong" but "should this land now". An agent working for hours
    needs the second one every turn, while stopping is still cheap.
    """
    from .harness.pacing import bar, pace

    added = sum(
        1 for line in diff.text.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )
    files = len({
        line.split()[-1] for line in diff.text.splitlines()
        if line.startswith("+++")
    })
    decision = pace(verdict, added, files, policy.structure.max_change_lines)
    paint = palette()
    tint = paint.amber if decision.value in ("overdue", "fix-first") else paint.steel
    print(f"\n{tint}{decision.value.upper():<10}{paint.reset} "
          f"{tint}{bar(decision)}{paint.reset}")
    print(f"           {paint.dim}{decision.reason}{paint.reset}")


def running_total(policy: Policy, root: str = ".") -> str:
    from . import ledger
    from .report import running_line
    from .totals import totals

    if not ledger.enabled(policy):
        return ""
    return running_line(totals(ledger.path_for(policy, root)))


def _dead_patterns(policy: Policy, root: str = ".") -> None:
    """Warn about configured paths that no longer match anything."""
    from .scan import unmatched_patterns

    patterns = getattr(policy.routing, "escalate_paths", ())
    for pattern in unmatched_patterns(root, patterns):
        print(
            f"policy warning: routing.escalate_paths pattern {pattern!r} matches "
            "no file in this repository; it is protecting nothing",
            file=sys.stderr,
        )


#: Skips worth naming one by one. Anything else is a file nobody expected a
#: rule to apply to, and listing those pushes the findings off the screen.
_NOTABLE_SKIPS = ("unparseable", "could not", "no exact analyser",
                  "lexically", "generated code", "binary")


def print_skips(notes) -> None:
    """Name the interesting skips; count the rest.

    "README.md: no rule applies" is true and useless — of course no rule
    applies to a README. A file that *could* have been analysed and was not is
    worth a line each; the rest are worth one line in total, so the fact stays
    visible without burying what the reader came for.
    """
    notable = [n for n in notes if any(k in n for k in _NOTABLE_SKIPS)]
    for note in notable:
        print(f"skipped: {note}", file=sys.stderr)
    rest = len(notes) - len(notable)
    if rest:
        print(f"skipped: {rest} file(s) no rule applies to (docs, config)",
              file=sys.stderr)


def palette():
    """Colour for stdout, or empty strings when it is not a terminal."""
    from .branding import palette as _resolve

    return _resolve(sys.stdout)


def has_contract(verdict) -> bool:
    return any(f.rule in _CONTRACT for f in verdict.findings)


def print_human(verdict: Verdict, policy: Policy) -> None:
    for warning in policy.warnings:
        print(f"policy warning: {warning}", file=sys.stderr)
    _dead_patterns(policy)
    print_skips(verdict.skipped)

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

    paint = palette()
    head = paint.amber if has_contract(verdict) else paint.bold
    print(f"{head}{verdict.status.value.upper()}{paint.reset}  "
          f"{len(verdict.findings)} finding(s)\n")
    for finding in verdict.findings:
        print(_finding(finding, paint))


def _finding(finding, paint) -> str:
    """One finding, with correctness picked out from taste.

    A long function and a broken assertion should not look the same at a
    glance, which is the only reason there is colour here at all.
    """
    symbol = f" in {finding.symbol}" if finding.symbol else ""
    rule = paint.amber if finding.rule in _CONTRACT else paint.dim
    return (
        f"  {paint.dim}{finding.file}:{finding.line}{symbol}{paint.reset}"
        f"  {rule}[{finding.rule}]{paint.reset}\n"
        f"    {finding.detail}\n"
        f"    {paint.dim}fix:{paint.reset} {finding.prescription}\n"
    )
    total = running_total(policy)
    if total:
        print(total)


__all__ = ["print_human", "print_skips", "print_pace", "running_total",
           "allow_notice", "palette"]
