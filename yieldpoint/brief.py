"""What an agent needs to know *before* it edits, not after.

A verdict arrives too late to be cheap. By the time a rule fires the model has
already written the code, and fixing it costs another turn — measurably more
than the check itself ever saves. The information that would have prevented the
finding was available the whole time; nobody asked for it.

This assembles that briefing. For the files a task is about to touch it reports
the headroom that remains, the functions already at their limit, the assertions
that must not get weaker, and the imports the file's zone forbids. All of it is
read off the syntax tree: no model call, no network.

It is deliberately short. A briefing that costs more context than the mistake
it prevents is not worth sending.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .core import glob
from .core.assertions import extract
from .core.metrics import measure
from .core.policy import Policy
from .history import History, fold, stale


@dataclass(frozen=True)
class Crowded:
    """A function with little or no room left."""

    name: str
    measure: str
    used: int
    limit: int

    @property
    def over(self) -> bool:
        return self.used > self.limit


@dataclass(frozen=True)
class FileBrief:
    path: str
    exists: bool
    lines: int = 0
    line_limit: int = 0
    protected: bool = False
    assertions: tuple[str, ...] = ()
    """Assertions in this file that must not get weaker. Listed, not counted:
    an agent told "seven assertions are protected" still has to guess which."""
    crowded: tuple[Crowded, ...] = ()
    zone: str = ""
    forbidden_imports: tuple[str, ...] = ()
    unreadable: str = ""

    repeats: tuple[tuple[str, int], ...] = ()
    """Rules that have already fired on this path, commonest first. The
    cheapest prediction there is: it is not a guess about what might go wrong
    here, it is a record of what did."""

    unchecked: bool = False
    """The file changed after the last time anything analysed it, so any
    finding the ledger holds for it may be stale in either direction."""

    never_checked: bool = False
    """Nothing has ever analysed this path. Not the same as analysed-and-clean,
    and must not be rendered as though it were (RULES.md section 5)."""

    @property
    def headroom(self) -> int:
        return max(0, self.line_limit - self.lines)


@dataclass(frozen=True)
class Brief:
    project: str
    files: tuple[FileBrief, ...] = ()
    change_budget: int = 0
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def anything_to_say(self) -> bool:
        """Whether a brief is worth sending at all.

        A file nothing has ever analysed counts. Saying "nothing to watch"
        about it would report an absence of looking as an absence of problems.
        """
        return any(f.protected or f.crowded or f.forbidden_imports or f.unreadable
                   or f.repeats or f.unchecked or (f.never_checked and f.exists)
                   for f in self.files)


#: How close to a limit counts as worth mentioning. Below this the agent has
#: room and saying so is noise; at or above it, one more addition trips a rule.
CROWDED_AT = 0.8


def _crowded(source: str, path: str, policy: Policy) -> tuple[Crowded, ...]:
    """Functions with no room left, so an agent does not add to them."""
    module = measure(source, filename=path)
    if not module.ok:
        return ()

    limits = (
        ("lines", policy.structure.max_lines),
        ("complexity", policy.structure.max_complexity),
        ("parameters", policy.structure.max_parameters),
        ("nesting", policy.structure.max_nesting),
    )
    found = []
    for function in module.functions:
        for name, limit in limits:
            if not limit:
                continue
            used = getattr(function, name, 0)
            if used >= limit * CROWDED_AT:
                found.append(Crowded(function.qualname, name, used, limit))
    return tuple(found)


def _assertions(source: str, path: str) -> tuple[str, ...]:
    """The assertions a change must not weaken, verbatim."""
    extraction = extract(source, filename=path)
    if not extraction.ok:
        return ()
    return tuple(
        assertion.raw for test in extraction.tests
        for assertion in test.assertions
        if assertion.relation.verifies_anything and assertion.raw
    )


def _zone(path: str, policy: Policy) -> tuple[str, tuple[str, ...]]:
    for zone in policy.boundaries.zones:
        if glob.matches(zone.path, path):
            return zone.name, tuple(zone.forbidden_imports)
    return "", ()


def for_file(path: str, policy: Policy, root: Path,
             record: History | None = None) -> FileBrief:
    """Everything decidable about one file before it is edited."""
    target = root / path
    zone, forbidden = _zone(path, policy)
    protected = policy.protects(path)
    # ``None`` means no ledger to consult, which is not the same as a ledger
    # that has never seen this path. Only the second is worth reporting.
    past = record or History()
    seen = {"repeats": past.repeats, "unchecked": stale(past, target),
            "never_checked": record is not None and not past.seen}

    if not target.is_file():
        # A file that does not exist yet still has a budget and a zone, and
        # those are exactly what a new file tends to break.
        return FileBrief(path=path, exists=False, protected=protected,
                         line_limit=policy.structure.max_file_lines,
                         zone=zone, forbidden_imports=forbidden, **seen)

    try:
        source = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return FileBrief(path=path, exists=True, unreadable=str(exc), **seen)

    if not path.endswith(".py"):
        # Saying "could not parse" about a file no analyser claims reports a
        # gap in coverage as a defect in the file. They are not the same. Other
        # rules (CI, boundaries) may still apply here, so this is a note about
        # structural measurement only, not a verdict on the file.
        return FileBrief(path=path, exists=True, protected=protected, zone=zone,
                         forbidden_imports=forbidden,
                         unreadable="size and complexity not measured for this "
                                    "file type", **seen)

    module = measure(source, filename=path)
    return FileBrief(
        path=path,
        exists=True,
        lines=module.code_lines if module.ok else 0,
        line_limit=policy.structure.max_file_lines,
        protected=protected,
        assertions=_assertions(source, path) if protected else (),
        crowded=_crowded(source, path, policy),
        zone=zone,
        forbidden_imports=forbidden,
        unreadable="" if module.ok else (module.error or ""),
        **seen,
    )


def _past(policy: Policy, root: Path) -> dict[str, History]:
    """What the ledger holds, or nothing if it cannot be read.

    A missing or corrupt ledger must not stop a brief: the rest of it is read
    from the files and is useful on its own.
    """
    from .ledger import load
    from .recording import path_for
    try:
        return fold(load(path_for(policy, root)))
    except (OSError, ValueError):
        return {}


def brief(paths, policy: Policy | str | dict | None = None,
          root: str | Path = ".") -> Brief:
    """Brief an agent on the files it is about to touch."""
    resolved = Policy.load(policy)
    base = Path(root)
    past = _past(resolved, base)
    return Brief(
        project=resolved.project_name,
        files=tuple(for_file(str(p), resolved, base,
                             past.get(str(p), History()) if past else None)
                    for p in paths),
        change_budget=resolved.structure.max_change_lines,
    )


__all__ = ["Brief", "FileBrief", "Crowded", "brief", "for_file"]
