"""What a change is being compared against, resolved and then said out loud.

Every structural rule now reports whether this change introduced a violation or
inherited one, and that answer is only as good as the revision it compared
with. Against the working tree's parent it answers "did this edit make it
worse". Against a branch's merge base it answers "does this pull request make
it worse" — a different question, with a different answer, from the same
command.

Detecting a repository's default branch is a guess. Every heuristic here is
wrong somewhere: a repository with no remote, a fork whose origin points at the
fork, a team that calls it `develop`. So the guess is never silent — whatever
is resolved is printed with how it was arrived at, because a wrong comparison
point that announces itself costs a reader one line, and a wrong one that hides
misattributes every finding in the run.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

#: Branch names to try when nothing in the repository says which is the trunk.
#: Order is deliberate: a remote's idea of the default outranks a local branch
#: of the same name, because the local one may be stale or unrelated.
_CANDIDATES = ("origin/main", "origin/master", "main", "master")


@dataclass(frozen=True)
class Basis:
    """The revision a change is measured from, and how that was decided."""

    revision: str = ""
    how: str = ""

    @property
    def known(self) -> bool:
        return bool(self.revision)

    def describe(self) -> str:
        if not self.known:
            return ("compared against the working tree's parent; no branch base "
                    "was resolved, so findings are attributed per edit, not per branch")
        return f"compared against {self.revision} ({self.how})"


def _run(args: list[str], root: Path):
    from .worktree import _git

    return _git(args, root)


def _ok(completed) -> str:
    return completed.stdout.strip() if completed and completed.returncode == 0 else ""


def _from_origin_head(root: Path) -> str:
    """What the remote says its default is — the only non-guess available."""
    found = _ok(_run(["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], root))
    return found


def _configured(root: Path) -> str:
    return _ok(_run(["config", "--get", "init.defaultBranch"], root))


def _exists(revision: str, root: Path) -> bool:
    return bool(_run(["rev-parse", "--verify", "--quiet", revision], root)
                and _ok(_run(["rev-parse", "--verify", "--quiet", revision], root)))


def default_branch(root: str | Path = ".") -> Basis:
    """The trunk this branch is presumed to have come from.

    Tried in order of how much each source actually knows, and the answer
    carries which one supplied it.
    """
    base = Path(root)
    remote = _from_origin_head(base)
    if remote:
        return Basis(remote, "the remote's default branch")

    configured = _configured(base)
    if configured and _exists(configured, base):
        return Basis(configured, "init.defaultBranch in git config")

    for candidate in _CANDIDATES:
        if _exists(candidate, base):
            return Basis(candidate, "a conventional name, since nothing declared one")
    return Basis()


def resolve(root: str | Path = ".", against: str = "") -> Basis:
    """What to compare with: what was asked for, or the trunk, or nothing.

    ``auto`` asks for detection explicitly. An empty value is not a request for
    detection — it means the working tree's parent, which is the right basis for
    "what did I just change" and the wrong one for "what does this branch do".
    """
    if against == "auto":
        return default_branch(root)
    if against:
        return Basis(against, "given on the command line")
    return Basis()


__all__ = ["Basis", "default_branch", "resolve"]
