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
        return any(f.protected or f.crowded or f.forbidden_imports or f.unreadable
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


def for_file(path: str, policy: Policy, root: Path) -> FileBrief:
    """Everything decidable about one file before it is edited."""
    target = root / path
    zone, forbidden = _zone(path, policy)
    protected = policy.protects(path)

    if not target.is_file():
        # A file that does not exist yet still has a budget and a zone, and
        # those are exactly what a new file tends to break.
        return FileBrief(path=path, exists=False, protected=protected,
                         line_limit=policy.structure.max_file_lines,
                         zone=zone, forbidden_imports=forbidden)

    try:
        source = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return FileBrief(path=path, exists=True, unreadable=str(exc))

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
    )


def brief(paths, policy: Policy | str | dict | None = None,
          root: str | Path = ".") -> Brief:
    """Brief an agent on the files it is about to touch."""
    resolved = Policy.load(policy)
    base = Path(root)
    return Brief(
        project=resolved.project_name,
        files=tuple(for_file(str(p), resolved, base) for p in paths),
        change_budget=resolved.structure.max_change_lines,
    )


__all__ = ["Brief", "FileBrief", "Crowded", "brief", "for_file"]
