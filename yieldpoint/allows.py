"""Every acknowledgement in the tree, and how long it has been there.

From the field review: *"the allow comment needs a lifecycle... otherwise
allows quietly becomes decorative."* That is the right worry. An escape hatch
with no inventory is indistinguishable from a disabled rule — nobody can tell
whether a project has three considered exceptions or three hundred reflexes,
and the count only ever goes one way.

Age comes from git, which knows when the line was written. That is a stored
fact about a commit, not a reading of the current clock, so the same tree gives
the same answer tomorrow (RULES.md section 4). Without git there is no age, and
that is reported as absent rather than guessed at.

Nothing here blocks. An inventory is for deciding, and deciding is a person's
job.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .core.acknowledge import scan
from .core.policy import Policy

#: git's blame is slow enough to be worth bounding; a tree with more
#: acknowledged files than this has a bigger problem than this report.
MAX_BLAMED_FILES = 200

_TIMEOUT = 20


@dataclass(frozen=True)
class Allow:
    """One acknowledgement, where it is and what is known about it."""

    file: str
    line: int
    rule: str
    reason: str
    written: str = ""
    """The commit date of the line, ``YYYY-MM-DD``, or empty when unknown."""

    author: str = ""
    """Who committed the line, per git."""

    until: str = ""
    """The date the author wrote it should stop being acceptable, as written.
    Never judged except by ``--expired``, which says it is reading the clock."""

    owner: str = ""
    """Who the debt belongs to, as declared. Distinct from ``author``: the
    person who wrote the acknowledgement is often not the one who owns the
    fix, and making the last person to trip over it responsible is how debt
    gets acknowledged rather than assigned."""

    @property
    def dated(self) -> bool:
        return bool(self.written)

    @property
    def expires(self) -> bool:
        return bool(self.until)


def _blame(root: Path, relative: str) -> dict[int, tuple[str, str]]:
    """Line number to (date, author) for one file, or nothing if git cannot say."""
    try:
        done = subprocess.run(
            ["git", "blame", "--line-porcelain", "--", relative],
            cwd=str(root), capture_output=True, text=True,
            timeout=_TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError):
        return {}
    if done.returncode != 0:
        return {}
    return _parse_blame(done.stdout)


#: A porcelain header: <40-char sha> <original line> <final line> [count].
_SHA_LENGTH = 40


def _header_line(row: str) -> int | None:
    """The final line number a porcelain header announces, if it is one."""
    parts = row.split()
    if len(parts) < 3 or len(parts[0]) != _SHA_LENGTH or not parts[2].isdigit():
        return None
    return int(parts[2])


def _parse_blame(text: str) -> dict[int, tuple[str, str]]:
    """``--line-porcelain`` output: a header, then fields, then the line itself."""
    out: dict[int, tuple[str, str]] = {}
    line, author, when = 0, "", ""
    for row in text.splitlines():
        if row.startswith("author "):
            author = row[7:].strip()
        elif row.startswith("author-time "):
            when = _date(row[12:].strip())
        elif not row.startswith("\t"):
            line = _header_line(row) or line
        elif line:
            out[line] = (when, author)
    return out


def _date(epoch: str) -> str:
    """The commit's own timestamp, formatted. Not a reading of now."""
    import datetime

    try:
        moment = datetime.datetime.fromtimestamp(int(epoch), datetime.timezone.utc)
    except (ValueError, OSError, OverflowError):
        return ""
    return moment.strftime("%Y-%m-%d")


def collect(root: str | Path = ".", policy: Policy | None = None) -> list[Allow]:
    """Every acknowledgement under ``root``, oldest first where dates are known."""
    from .scan import walk

    base = Path(root)
    resolved = policy or Policy()
    found: list[Allow] = []
    blamed = 0
    for path in walk(base, resolved):
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        marks = scan(source)
        if not marks:
            continue
        relative = str(path.relative_to(base))
        dates = {}
        if blamed < MAX_BLAMED_FILES:
            dates = _blame(base, relative)
            blamed += 1
        for line, entries in sorted(marks.items()):
            when, author = dates.get(line, ("", ""))
            found.extend(
                Allow(relative, line, mark.rule, mark.reason, when, author,
                      until=mark.until, owner=mark.owner)
                for mark in entries)
    # Undated last: a missing date is not "written at the epoch".
    return sorted(found, key=lambda a: (not a.dated, a.written, a.file, a.line))


def _written(allow: Allow) -> str:
    """When it was written, who owns it, and when they said it should end."""
    parts = [allow.written or "date unknown"]
    if allow.owner:
        parts.append(f"owner {allow.owner}")
    elif allow.author:
        parts.append(allow.author)
    if allow.until:
        parts.append(f"until {allow.until}")
    return ", ".join(parts)


def _group(found: list[Allow]) -> dict[str, list[Allow]]:
    out: dict[str, list[Allow]] = {}
    for allow in found:
        out.setdefault(allow.rule, []).append(allow)
    return out


def render(found: list[Allow]) -> str:
    """The inventory. Oldest first, because age is the thing worth noticing."""
    if not found:
        return ("No acknowledgements in this tree. Every rule that fired was "
                "either fixed or is still reported.")
    undated = sum(1 for a in found if not a.dated)
    lines = [f"{len(found)} acknowledgement(s), oldest first", ""]
    for rule, entries in sorted(_group(found).items(),
                                key=lambda item: (-len(item[1]), item[0])):
        lines.append(f"  {rule}  ({len(entries)})")
        for allow in entries:
            lines.append(f"    {_written(allow)}  {allow.file}:{allow.line}")
            lines.append(f"      {allow.reason[:96]}")
        lines.append("")
    if undated:
        lines.append(f"  {undated} have no date: not committed yet, or git "
                     f"could not say. Not treated as new.")
    dated = sum(1 for a in found if a.expires)
    lines.append(f"  {dated} carry an expiry. It is never enforced here: an "
                 f"acknowledgement that stopped")
    lines.append("  working overnight would make the same commit pass today "
                 "and fail tomorrow.")
    lines.append("  Run `yieldpoint allows --expired` — which does read the "
                 "clock — to enforce them.")
    lines.append("  Dates are the commit's, not today's — this report is the "
                 "same tomorrow.")
    lines.append("  An acknowledgement answers one rule at one place. It is "
                 "not an off switch,")
    lines.append("  and a file that gets worse despite one is still reported.")
    return "\n".join(lines)


def to_dict(found: list[Allow]) -> dict:
    return {"acknowledgements": [
        {"file": a.file, "line": a.line, "rule": a.rule, "reason": a.reason,
         "written": a.written, "author": a.author, "until": a.until,
         "owner": a.owner} for a in found]}


#: Exit code when an expiry has passed. Distinct from 2, which means the
#: command itself could not run.
EXIT_EXPIRED = 1


def expired(found: list[Allow], today: str) -> tuple[list[Allow], list[Allow]]:
    """Which acknowledgements are past their date, and which cannot be judged.

    ``today`` is passed in rather than read, so this function stays testable
    and stays honest: the clock is read once, at the edge, by the command that
    advertises that it does.
    """
    past, unreadable = [], []
    for allow in found:
        if not allow.expires:
            continue
        if not _is_date(allow.until):
            unreadable.append(allow)
        elif allow.until < today:
            past.append(allow)
    return past, unreadable


def _is_date(text: str) -> bool:
    import datetime

    try:
        datetime.date.fromisoformat(text)
    except ValueError:
        return False
    return True


def render_expired(past: list[Allow], unreadable: list[Allow], today: str) -> str:
    """What has run out, said plainly, with the date it was judged against."""
    lines = [f"Judged against {today}, read from this machine's clock. "
             f"The same tree gives a different answer on a different day."]
    if not past and not unreadable:
        return "\n".join(lines + ["", "No acknowledgement has passed its date."])
    for allow in past:
        owner = f" ({allow.owner})" if allow.owner else ""
        lines.append(f"  expired {allow.until}{owner}  {allow.file}:{allow.line} "
                     f"[{allow.rule}]")
        lines.append(f"    {allow.reason[:88]}")
    for allow in unreadable:
        lines.append(f"  unreadable date {allow.until!r}  {allow.file}:"
                     f"{allow.line} [{allow.rule}]")
    if unreadable:
        lines.append("  A date this cannot parse is not an expiry that passed, "
                     "and not one that did not.")
    return "\n".join(lines)


def allows_command(args) -> int:
    import json
    import sys

    try:
        policy = Policy.load(args.policy, root=args.root)
    except (OSError, ValueError) as exc:
        print(f"yieldpoint: {exc}", file=sys.stderr)
        return 2
    found = collect(args.root, policy)
    if args.rule:
        found = [a for a in found if a.rule in set(args.rule)]
    if getattr(args, "expired", False):
        import datetime

        today = datetime.date.today().isoformat()
        past, unreadable = expired(found, today)
        print(render_expired(past, unreadable, today))
        return EXIT_EXPIRED if past else 0
    print(json.dumps(to_dict(found), indent=2) if args.json else render(found))
    return 0


def add_command(sub) -> None:
    command = sub.add_parser(
        "allows", help="every acknowledgement in the tree, and how old it is")
    command.add_argument("--root", default=".")
    command.add_argument("--policy", default=None)
    command.add_argument("--rule", action="append", help="only this rule")
    command.add_argument("--json", action="store_true")
    command.add_argument("--expired", action="store_true",
                         help="read today's date and fail if an expiry has "
                              "passed; the only command here that reads a clock")
    command.set_defaults(handler=allows_command)


__all__ = ["Allow", "collect", "render", "to_dict", "allows_command", "add_command"]
