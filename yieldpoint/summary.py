"""The findings, written for a pull request rather than a terminal.

Rendered as Markdown because that is what a code-review platform shows to
people who did not install this tool and will not read its documentation. They
get one screen, once, next to a change they are deciding about.

So the structure is the answer to their question, not a list of rules: **what
did this change do**, separately from **what it walked into**. That split is
the entire point of the baselining work. A comment that cannot make it is back
to blaming a change for the file it happened to touch, which is the complaint
this all started from.

Nothing here decides anything. It renders a verdict somebody else produced.
"""

from __future__ import annotations

from .core.verdict import Status

#: Findings past this are summarised rather than listed. A comment longer than
#: the diff it is about does not get read, and the ones that matter are at the
#: top by construction: introduced before inherited.
MAX_LISTED = 15

_HEADING = "### Yieldpoint"


def _location(finding) -> str:
    where = f"`{finding.file}:{finding.line}`"
    return f"{where} in `{finding.symbol}`" if finding.symbol else where


def _item(finding) -> list[str]:
    out = [f"- **{finding.rule}** — {_location(finding)}", f"  {finding.detail}"]
    if finding.prescription:
        out.append(f"  _{finding.prescription}_")
    return out


def _section(title: str, findings: list, note: str = "") -> list[str]:
    if not findings:
        return []
    out = ["", f"#### {title} — {len(findings)}"]
    if note:
        out.append(f"{note}")
    for finding in findings[:MAX_LISTED]:
        out.extend(_item(finding))
    if len(findings) > MAX_LISTED:
        out.append(f"- … and {len(findings) - MAX_LISTED} more")
    return out


def _unevaluated(skipped) -> list[str]:
    """Files no rule could read, which are not the same as files that passed."""
    if not skipped:
        return []
    out = ["", f"#### Not evaluated — {len(skipped)}",
           "No rule in this policy could analyse these. That is not a pass."]
    out.extend(f"- {note}" for note in skipped[:MAX_LISTED])
    if len(skipped) > MAX_LISTED:
        out.append(f"- … and {len(skipped) - MAX_LISTED} more")
    return out


def _headline(introduced: list, inherited: list, basis: str) -> list[str]:
    if not introduced and not inherited:
        return [_HEADING, "", "Nothing this change did weakens what the tests "
                             "verify, and no limit was crossed.", ""]
    counted = []
    if introduced:
        counted.append(f"**{len(introduced)} introduced by this change**")
    if inherited:
        counted.append(f"{len(inherited)} inherited")
    tail = f" Compared against {basis}." if basis else ""
    return [_HEADING, "", ", ".join(counted) + "." + tail]


def render(verdict, *, basis: str = "") -> str:
    """One comment. Safe to post when there is nothing to say."""
    findings = list(verdict.findings)
    introduced = [f for f in findings if not f.inherited]
    inherited = [f for f in findings if f.inherited]

    lines = _headline(introduced, inherited, basis)
    lines.extend(_section("Introduced by this change", introduced))
    lines.extend(_section(
        "Already over before this change", inherited,
        "Listed so the trend stays visible. These are not this change's debt — "
        "the fix is owed, but not here and not now."))
    lines.extend(_unevaluated(list(verdict.skipped)))
    if verdict.status is Status.UNVERIFIED:
        lines.extend(["", "**Nothing was analysed.** This is not a pass — no "
                          "rule in this policy could read the change."])
    return "\n".join(lines).rstrip() + "\n"


def summary_command(args) -> int:
    """Render the last review as Markdown, for a PR comment or a job summary."""
    from .basis import resolve
    from .commands import EXIT_ERROR, EXIT_OK, _use_cache_for
    from .core.policy import Policy
    from .verify import verify_diff
    from .worktree import uncommitted

    try:
        policy = Policy.load(args.policy, root=args.root)
    except (OSError, ValueError) as exc:
        print(f"yieldpoint: {exc}")
        return EXIT_ERROR

    _use_cache_for(args.root)
    basis = resolve(args.root, args.against or "")
    diff = uncommitted(args.root, staged=args.staged, against=basis.revision)
    if not diff.ok:
        print(f"{_HEADING}\n\n{diff.reason}.\n")
        return EXIT_OK
    verdict = verify_diff(diff.text, root=diff.root, policy=policy)
    print(render(verdict, basis=f"`{basis.revision}`" if basis.known else ""))
    return EXIT_OK


def add_command(sub) -> None:
    command = sub.add_parser(
        "summary", help="the review as Markdown, for a pull-request comment")
    command.add_argument("--root", default=".")
    command.add_argument("--policy", default=None)
    command.add_argument("--against", default="")
    command.add_argument("--staged", action="store_true")
    command.set_defaults(handler=summary_command)


__all__ = ["render", "summary_command", "add_command"]
