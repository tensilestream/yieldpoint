"""What this build can actually read, counted against this repository.

From the field review: *"90% of developers means TS/JS, Python, Java, Go, C#,
Rust, Kotlin, Swift, PHP, Ruby... If it only handles Python, it's a Python
tool."* True, and the useful response is not a feature matrix in a README. It
is a number from the reader's own tree: of the files you have, here is the
share anything here can analyse.

A repository is allowed to conclude from that number that this is not for it
yet. That is a better outcome than installing it, seeing `ok` on a change that
touched nothing analysable, and believing the change was checked.

Extensions only. Guessing a language from file contents would make the answer
depend on the sample; the extension is what the analyser dispatches on anyway,
so it is the honest unit.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .core import glob
from .core.contract import EXACT_SUFFIXES
from .core.policy import Policy

#: Everything a Python file gets: the test contract, the structure limits,
#: refactor safety, boundaries and the swallowed-exception rule.
FULL = "every rule"

#: Matched by path rather than extension — a workflow file is checked for a
#: weakened build whatever it is called.
CI_ONLY = "build-integrity rules only"

#: No analyser claims it. Reported as skipped on every run, never as a pass.
NONE = "not evaluated"

#: Files that are not source and should not dilute the count — a repository is
#: not less covered because it contains a licence and a changelog.
NOT_SOURCE = frozenset({
    ".md", ".rst", ".txt", ".json", ".toml", ".cfg", ".ini", ".lock",
    ".svg", ".png", ".jpg", ".ico", ".gif", ".pdf", ".csv", ".html", ".css",
    # Data and runtime artefacts. Counting a SQLite journal as an unanalysed
    # source file would make every repository look less covered than it is.
    ".db", ".sqlite3", ".jsonl", ".log", ".pid", ".tag", ".pyc", ".vsix",
    ".db-shm", ".db-wal", ".sqlite3-shm", ".sqlite3-wal", ".yieldpoint-backup",
    ".map", ".typed",
})

#: Directories this tool writes into. Surveying its own output would report a
#: repository as less covered the longer Yieldpoint had been running in it.
OURS = ("**/.yieldpoint/**", ".yieldpoint/**")


@dataclass(frozen=True)
class Coverage:
    """One extension, how many files carry it, and what they get."""

    extension: str
    files: int
    depth: str

    @property
    def analysed(self) -> bool:
        return self.depth is not NONE


def depth_for(path: str, policy: Policy) -> str:
    if path.endswith(EXACT_SUFFIXES):
        return FULL
    if glob.matches_any(policy.ci.paths, path):
        return CI_ONLY
    return NONE


def _every_file(base: Path, policy: Policy):
    """Every file the policy does not ignore — not only the analysable ones.

    Deliberately not ``scan.walk``, which filters to the extensions this build
    analyses. Surveying coverage with it reported 100% on every repository
    ever, because the only files it could see were the ones already covered.
    A measurement that cannot return a bad answer is not a measurement.
    """
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        relative = str(path.relative_to(base))
        if glob.matches_any(tuple(policy.scan.ignore) + OURS, relative):
            continue
        yield path, relative


def survey(root: str | Path = ".", policy: Policy | None = None) -> list[Coverage]:
    """Every extension in the tree, commonest first."""
    base = Path(root)
    resolved = policy or Policy()
    counts: Counter[tuple[str, str]] = Counter()
    for path, relative in _every_file(base, resolved):
        suffix = path.suffix.lower()
        # A file with no extension cannot be classified by the only signal
        # this uses, and guessing from contents would make the answer depend
        # on the sample. Left out rather than counted as uncovered.
        if not suffix or suffix in NOT_SOURCE:
            continue
        counts[(suffix, depth_for(relative, resolved))] += 1
    return [Coverage(suffix, count, depth)
            for (suffix, depth), count in counts.most_common()]


def _by_extension(found: list[Coverage]) -> list[tuple[str, list[Coverage]]]:
    """One line per extension, even when its files are covered differently.

    A workflow file and an ordinary YAML file share an extension and get very
    different treatment; two rows reading `.yml` invite the reader to think one
    of them is a mistake.
    """
    grouped: dict[str, list[Coverage]] = {}
    for entry in found:
        grouped.setdefault(entry.extension, []).append(entry)
    return sorted(grouped.items(),
                  key=lambda item: (-sum(e.files for e in item[1]), item[0]))


def _share(found: list[Coverage]) -> tuple[int, int]:
    total = sum(c.files for c in found)
    return sum(c.files for c in found if c.analysed), total


def render(found: list[Coverage]) -> str:
    """The matrix, and the one number that answers the question."""
    if not found:
        return "No source files found to survey."
    lines = ["COVERAGE IN THIS REPOSITORY  source files, by extension", ""]
    for extension, entries in _by_extension(found):
        total = sum(e.files for e in entries)
        depth = " / ".join(f"{e.files} {e.depth}" for e in entries) \
            if len(entries) > 1 else entries[0].depth
        lines.append(f"  {extension:<14} {total:>5} files   {depth}")
    covered, total = _share(found)
    lines.append("")
    lines.append(f"  {covered:,} of {total:,} source files ({covered / total:.0%}) "
                 f"are analysed by this build.")
    if covered < total:
        lines.append("  The rest are reported as not evaluated on every run — "
                     "never as a pass.")
    lines.append("  Python is the only language analysed exactly today. That is "
                 "the honest limit,")
    lines.append("  and a repository is allowed to decide this is not for it yet.")
    return "\n".join(lines)


def to_dict(found: list[Coverage]) -> dict:
    covered, total = _share(found)
    return {
        "source_files": total,
        "analysed": covered,
        "by_extension": [
            {"extension": c.extension, "files": c.files, "depth": c.depth}
            for c in found],
    }


def languages_command(args) -> int:
    import json
    import sys

    try:
        policy = Policy.load(args.policy, root=args.root)
    except (OSError, ValueError) as exc:
        print(f"yieldpoint: {exc}", file=sys.stderr)
        return 2
    found = survey(args.root, policy)
    print(json.dumps(to_dict(found), indent=2) if args.json else render(found))
    return 0


def add_command(sub) -> None:
    command = sub.add_parser(
        "languages", help="how much of this repository this build can analyse")
    command.add_argument("--root", default=".")
    command.add_argument("--policy", default=None)
    command.add_argument("--json", action="store_true")
    command.set_defaults(handler=languages_command)


__all__ = ["Coverage", "survey", "render", "to_dict", "depth_for",
           "languages_command", "add_command"]
