"""Getting a diff out of git, so that "check my work" takes no arguments.

Every other entry point asks the caller to supply the change: before and after
content, or a unified diff on stdin. That is the right shape for a library and
the wrong shape for a person at a terminal or an agent that has just finished
editing — both of them already made the change, and want to know what it broke.

**This is a surface, not a check.** RULES.md section 4 forbids environment reads
inside the verification path; running ``git`` is how the *input* is obtained,
exactly as ``git diff | yieldpoint check --diff -`` already does. The verdict
itself is computed by the same pure engine from the same diff text, so it stays
reproducible: given the diff, the answer does not depend on git being present.

Nothing here raises. A missing git, a directory that is not a repository, and a
repository with no changes are all ordinary answers, not failures.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

#: Long enough for a large repository, short enough that a hung git does not
#: hang an editor's MCP connection.
TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class Diff:
    """A unified diff, or the reason there is not one."""

    text: str = ""
    reason: str = ""
    root: str = "."

    @property
    def ok(self) -> bool:
        return bool(self.text)


def uncommitted(root: str | Path = ".", *, staged: bool = False,
                against: str = "") -> Diff:
    """The change not yet committed, as a unified diff.

    ``staged`` limits it to what is staged; ``against`` compares with a branch or
    commit instead, for reviewing a whole branch rather than a working tree.
    """
    base = Path(root)
    top = _toplevel(base)
    if top is None:
        return Diff(reason=f"{base} is not inside a git repository", root=str(base))

    completed = _git(_diff_args(staged=staged, against=against), top)
    problem = _ran(completed)
    if problem:
        return Diff(reason=problem, root=str(top))

    text = completed.stdout
    if not against and not staged:
        text += _untracked(top)

    # Emptiness is judged *after* untracked files are added. Checking first
    # would report "nothing to check" for a change consisting only of new
    # files — which is the most interesting change an agent makes.
    if not text.strip():
        scope = "staged" if staged else ("branch" if against else "uncommitted")
        return Diff(reason=f"no {scope} changes to check{_also_dirty(top, against)}",
                    root=str(top))
    return Diff(text=text, root=str(top))


def _diff_args(*, staged: bool, against: str) -> list[str]:
    args = ["diff", "--no-color", "--no-ext-diff", "-U3"]
    if against:
        args.append(f"{against}...")
    elif staged:
        args.append("--cached")
    return args


def _ran(completed) -> str:
    """Why git could not produce a diff at all, or empty when it did."""
    if completed is None:
        return "git is not available on PATH"
    if completed.returncode != 0:
        detail = (completed.stderr or "").strip().splitlines()
        return f"git diff failed: {detail[0] if detail else 'unknown error'}"
    return ""


def _also_dirty(top: Path, against: str) -> str:
    """Warn when a branch review found nothing while the tree is not clean.

    ``git diff <rev>...`` compares the merge base with HEAD, so work that is
    only in the working tree is outside the question being asked. That is
    correct and it is surprising: being told there is nothing to check while
    holding unsaved edits reads as the tool failing to see them.
    """
    if not against:
        return ""
    listing = _git(["status", "--porcelain"], top)
    if listing is None or listing.returncode != 0 or not listing.stdout.strip():
        return ""
    return (" — uncommitted work is not part of a branch comparison; "
            "run without --against to check it")


def _untracked(top: Path) -> str:
    """Diffs for new files, which ``git diff`` omits until they are staged.

    A newly written test file is the most interesting thing an agent produces,
    so leaving it out would mean the most common case is the one not checked.
    """
    listing = _git(["ls-files", "--others", "--exclude-standard"], top)
    if listing is None or listing.returncode != 0:
        return ""
    out = []
    for name in listing.stdout.splitlines():
        if not name.strip():
            continue
        added = _git(["diff", "--no-color", "--no-index", "-U3", os.devnull, name], top)
        if added is not None and added.stdout:
            out.append(added.stdout)
    return "".join(out)


def _toplevel(base: Path) -> Path | None:
    completed = _git(["rev-parse", "--show-toplevel"], base)
    if completed is None or completed.returncode != 0:
        return None
    found = completed.stdout.strip()
    return Path(found) if found else None


def at_head(path: str | Path, root: str | Path = ".") -> str | None:
    """The committed content of one file, or ``None`` if it has none.

    ``None`` covers every way a file can be absent from ``HEAD`` — untracked,
    newly added, outside a repository, git unavailable — because a caller
    asking "was this already committed?" wants the same answer for all of them.
    """
    base = Path(root)
    top = _toplevel(base)
    if top is None:
        return None
    try:
        relative = Path(path).resolve().relative_to(top.resolve()).as_posix()
    except (ValueError, OSError):
        relative = str(path)
    completed = _git(["show", f"HEAD:{relative}"], top)
    if completed is None or completed.returncode != 0:
        return None
    return completed.stdout


def _git(args: list[str], cwd: Path):
    """Run git, returning ``None`` when it cannot be run at all."""
    try:
        return subprocess.run(
            ["git", *args], cwd=str(cwd), capture_output=True,
            text=True, timeout=TIMEOUT_SECONDS, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None


__all__ = ["Diff", "uncommitted", "at_head", "TIMEOUT_SECONDS"]
