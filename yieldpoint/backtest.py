"""What would this have said about work you already did?

The question anyone sensible asks before switching on a gate is not "what is
your false-positive rate" — it is "what would you have done to *my* repository".
Thirty-seven curated fixtures cannot answer that. Your own history can.

    yieldpoint backtest --since HEAD~200

Each commit is replayed as the change it was, verified against the state it
started from, and reported. The output is a rate measured on real work by the
people who wrote it, which is the only number worth trusting before adoption.

**It cannot tell a true finding from a false one.** Nobody can, mechanically —
that is the judgement being asked for. What it does is put every finding in
front of a person cheaply, with the commit that produced it, so the judgement
can be made on evidence instead of on a vendor's fixtures.

Read-only. Nothing here writes to the repository or changes a reference; the
worktree is never touched, because file contents come from ``git show``.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .core.policy import Policy
from .core.verdict import Status, Verdict
from .verify import verify_diff

TIMEOUT_SECONDS = 60

#: Rules that mean the change weakened what the suite verifies. Reported apart
#: from the maintainability rules, because they are adopted differently: these
#: are worth gating on from day one, and a length limit is a conversation about
#: taste that should not hold up the gate.
CONTRACT_RULES = frozenset({
    "assertion_monotonicity", "vacuous_assertion", "empty_test",
    "skip_marker", "disabled_assertion", "dangling_reference",
    "export_removed", "ci_check_removed", "ci_check_disabled",
    "boundary_violation",
})


@dataclass(frozen=True)
class CommitResult:
    """One replayed commit."""

    sha: str
    subject: str
    verdict: Verdict

    @property
    def flagged(self) -> bool:
        return self.verdict.status not in (Status.PASS, Status.UNVERIFIED)

    @property
    def rules(self) -> tuple[str, ...]:
        return tuple(sorted({f.rule for f in self.verdict.findings}))

    @property
    def contract_rules(self) -> tuple[str, ...]:
        return tuple(r for r in self.rules if r in CONTRACT_RULES)


@dataclass(frozen=True)
class Backtest:
    """What the whole replay found."""

    commits: tuple[CommitResult, ...] = ()
    unreadable: tuple[str, ...] = ()
    reason: str = ""

    @property
    def flagged(self) -> tuple[CommitResult, ...]:
        return tuple(c for c in self.commits if c.flagged)

    @property
    def rate(self) -> float:
        return len(self.flagged) / len(self.commits) if self.commits else 0.0

    @property
    def contract_flagged(self) -> tuple[CommitResult, ...]:
        """Commits a correctness rule would have stopped."""
        return tuple(c for c in self.commits if c.contract_rules)

    @property
    def contract_rate(self) -> float:
        if not self.commits:
            return 0.0
        return len(self.contract_flagged) / len(self.commits)

    def by_rule(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for commit in self.flagged:
            for rule in commit.rules:
                counts[rule] = counts.get(rule, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def run(root: str | Path = ".", since: str = "HEAD~50",
        policy: Policy | str | dict | None = None,
        limit: int = 500, progress=None) -> Backtest:
    """Replay every commit in ``since..HEAD``, oldest first."""
    base = Path(root)
    resolved = Policy.load(policy)

    # A replay reads the same files at many commits. Content-addressed caching
    # is what makes that affordable: an unchanged file is analysed once for the
    # whole range, not once per commit that touched its neighbours.
    from .core.locate import repository
    from .core.parsecache import configure

    configure(repository(base))
    shas = _commits(base, since, limit)
    if isinstance(shas, str):
        return Backtest(reason=shas)

    results = []
    unreadable = []
    for index, (sha, subject) in enumerate(shas, start=1):
        if progress:
            progress(index, len(shas), sha[:8])
        verdict = _replay(base, sha, resolved)
        if verdict is None:
            unreadable.append(sha)
            continue
        results.append(CommitResult(sha=sha, subject=subject, verdict=verdict))

    return Backtest(commits=tuple(results), unreadable=tuple(unreadable))


def _commits(base: Path, since: str, limit: int):
    """``(sha, subject)`` oldest first, or a string explaining why not."""
    listed = _git(base, ["log", "--format=%H%x00%s", "--reverse",
                         f"--max-count={limit}", f"{since}..HEAD"])
    if listed is None:
        return "git is not available on PATH"
    if listed.returncode != 0:
        detail = (listed.stderr or "").strip().splitlines()
        return f"could not list commits: {detail[0] if detail else 'unknown error'}"

    rows = []
    for line in listed.stdout.splitlines():
        sha, _, subject = line.partition("\0")
        if sha.strip():
            rows.append((sha.strip(), subject.strip()))
    if not rows:
        return f"no commits in {since}..HEAD"
    return rows


def _replay(base: Path, sha: str, policy: Policy) -> Verdict | None:
    """Verify one commit as the change it was when it was made."""
    shown = _git(base, ["show", "--no-color", "--no-ext-diff", "-U3",
                        "--format=", sha])
    if shown is None or shown.returncode != 0 or not shown.stdout.strip():
        return None

    def read(relative: str) -> str | None:
        """The file as it stood *after* that commit, not as it stands now."""
        blob = _git(base, ["show", f"{sha}:{relative}"])
        if blob is None or blob.returncode != 0:
            return None
        return blob.stdout

    try:
        return verify_diff(shown.stdout, base, policy, read=read)
    except Exception:  # one bad commit must not end the replay
        return None


def _git(base: Path, args: list[str]):
    try:
        return subprocess.run(
            ["git", *args], cwd=str(base), capture_output=True,
            text=True, timeout=TIMEOUT_SECONDS, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def render(result: Backtest, since: str) -> str:
    """The report. Two rates, because they are adopted at different speeds."""
    if result.reason:
        return f"yieldpoint: {result.reason}"
    if not result.commits:
        return f"No commits replayed for {since}..HEAD."

    total = len(result.commits)
    lines = [
        f"Replayed {total} commit(s) from {since}..HEAD, as the changes they were.",
        "",
        "  CORRECTNESS — the rules worth gating on from day one",
        f"    commits flagged        {len(result.contract_flagged):>5} / {total}"
        f"   ({result.contract_rate:.0%})",
        "",
        "  MAINTAINABILITY — limits, which are a matter of taste and tuning",
        f"    commits flagged        {len(result.flagged) - len(result.contract_flagged):>5}"
        f" / {total}",
        "",
        "  by rule",
    ]
    for rule, count in result.by_rule().items():
        mark = "  *" if rule in CONTRACT_RULES else "   "
        lines.append(f"   {mark} {rule:<26} {count:>5}")
    lines += ["", "    * correctness rule", ""]

    if result.contract_flagged:
        lines.append("  Commits a correctness rule would have stopped:")
        for commit in result.contract_flagged[:20]:
            lines.append(
                f"    {commit.sha[:10]}  {commit.subject[:46]:<46} "
                f"{', '.join(commit.contract_rules)}"
            )
        if len(result.contract_flagged) > 20:
            lines.append(f"    ... and {len(result.contract_flagged) - 20} more")
        lines.append("")

    lines += [
        "  Look at those commits. Yieldpoint cannot tell you which findings were",
        "  right — that judgement is the point of running this. What it can do is",
        "  put them in front of you cheaply, on your own work, before you switch",
        "  anything on.",
    ]
    if result.unreadable:
        lines.append(f"\n  {len(result.unreadable)} commit(s) could not be replayed "
                     "(merge commits and binary-only changes are skipped).")
    return "\n".join(lines)


__all__ = ["Backtest", "CommitResult", "run", "render", "CONTRACT_RULES"]
