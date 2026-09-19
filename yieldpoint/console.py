# yieldpoint: allow export_removed - `allow_notice` was named in __all__ but never defined in this module, so `import *` raised on it; nothing could have imported it.
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


#: What each status asks the reader to do next, in the imperative. An agent can
#: afford to read a finding and take another turn; a person whose commit just
#: stopped needs to be told what to do about it, on the screen, without going to
#: look anything up.
_ACTIONS = {
    Status.REPAIR: "Fix what each `fix:` line names above, then run `yieldpoint review` again.",
    Status.ESCALATE: "This needs a person to decide. Resolve it, then run `yieldpoint review` again.",
    Status.BLOCK: "Do not retry this change. Restore what each `fix:` line names above.",
    Status.UNVERIFIED: "Nothing was checked, so nothing here is a pass. Decide whether to proceed.",
}

#: Statuses that stop the reader rather than asking them to iterate.
_STOPS = frozenset({Status.BLOCK, Status.ESCALATE, Status.UNVERIFIED})


def report_link(policy: Policy, root: str = ".") -> str:
    """A clickable ``file://`` URL for the HTML report, or "" if none exists.

    Never written on demand: linking a page that is not there is worse than not
    linking one at all, and the Stop hook already refreshes it every turn.
    """
    from . import ledger

    try:
        page = ledger.path_for(policy, root).parent / "report.html"
        return page.as_uri() if page.is_file() else ""
    except (OSError, ValueError):
        return ""


def _headline_colour(verdict: Verdict, paint) -> str:
    """Red stops you, amber asks you to repair.

    The verdict word is coloured whatever the rule was, because at that moment
    it is the thing the reader has to act on. Whether the cause was a weakened
    contract or a matter of taste stays visible where it was always drawn — on
    the ``[rule]`` tag of each finding, amber or dim.
    """
    if verdict.status in _STOPS:
        return paint.red
    if verdict.findings:
        return paint.amber
    return paint.bold


def _next_step(verdict: Verdict, policy: Policy, paint, *,
               staged: bool, root: str) -> str:
    """The closing block: what to do, how to escape, where the detail is."""
    from .commands import only_maintainability

    if only_maintainability(verdict, policy):
        lines = [f"{paint.steel}→{paint.reset} Reported, not blocking. These describe "
                 f"shape, not a weakening."]
        lines.append(f"  {paint.dim}Set structure.gates true in .yieldpoint.json to make "
                     f"them binding.{paint.reset}")
        link = report_link(policy, root)
        if link:
            lines.append(f"  {paint.dim}Details:{paint.reset} {link}")
        return "\n".join(lines)

    action = _ACTIONS.get(verdict.status, "")
    if not action:
        return ""
    tint = paint.red if verdict.status in _STOPS else paint.amber
    lines = [f"{tint}→{paint.reset} {action}"]
    if staged:
        lines.append(f"  {paint.dim}This stopped a commit. To record it anyway:"
                     f" git commit --no-verify{paint.reset}")
    link = report_link(policy, root)
    if link:
        lines.append(f"  {paint.dim}Details:{paint.reset} {link}")
    return "\n".join(lines)


def print_human(verdict: Verdict, policy: Policy, *,
                staged: bool = False, root: str = ".") -> None:
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
        paint = palette()
        print(f"{paint.red}UNVERIFIED{paint.reset}  "
              "no rule could analyse this change; see skipped above")
        print(_next_step(verdict, policy, paint, staged=staged, root=root))
        return

    paint = palette()
    from .commands import only_maintainability

    head = (paint.dim if only_maintainability(verdict, policy)
            else _headline_colour(verdict, paint))
    print(f"{head}{verdict.status.value.upper()}{paint.reset}  "
          f"{len(verdict.findings)} finding(s)\n")
    for finding in verdict.findings:
        print(_finding(finding, paint))
    print(_next_step(verdict, policy, paint, staged=staged, root=root))


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


__all__ = ["print_human", "print_skips", "print_pace", "running_total",
           "report_link", "palette"]
