"""What is measurably true about a proposed change.

Routing and gating both need the same facts, and neither should recompute them.
Everything here is read off the source or the syntax tree: no model, no network,
no clock. A fact that cannot be established — an unparseable file, a language
with no analyser — is left ``None`` rather than assumed, because the decisions
built on top are only as honest as this.

The costly-looking ones are not. Parsing a file is a low single-digit
millisecond operation, which is four orders of magnitude cheaper than asking a
model the same question and does not vary between runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core import glob, metrics, symbols
from ..core.generated import detect
from ..core.policy import Policy

TEST_SUFFIXES = ("_test.py", "_spec.py")


@dataclass(frozen=True)
class Change:
    """A proposed edit. ``before`` is None for a new file, ``after`` for a delete."""

    path: str
    before: str | None = None
    after: str | None = None
    task: str = ""
    """What the agent was asked to do, if the harness knows. Never parsed for
    meaning — carried so a decision can be logged next to its cause."""


@dataclass(frozen=True)
class Signals:
    """Measured facts about one change. ``None`` means "could not tell"."""

    path: str = ""
    added_lines: int = 0
    removed_lines: int = 0
    touches_protected_test: bool = False
    touches_generated: bool = False
    analysable: bool = False
    parses: bool | None = None
    max_complexity: int | None = None
    max_function_lines: int | None = None
    file_lines: int | None = None
    exported_names: int | None = None
    imports: int | None = None
    new_dependencies: tuple[str, ...] = ()
    depended_on_by: int | None = None
    """How many modules in this repository import this one. ``None`` when no
    import graph was supplied — not zero, which would read as "nothing needs
    it" and quietly lower the risk of a load-bearing file."""

    importance: float | None = None
    """Where that fan-in sits in this repository's own distribution, 0..1.
    A percentile rather than a count, so one default works for a fifty-file
    service and a five-thousand-file monolith."""

    structural: bool | None = None
    """True when the change alters structure rather than only text — a renamed
    or removed definition, a new import. A docstring edit is not structural."""

    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def churn(self) -> int:
        return self.added_lines + self.removed_lines

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "added_lines": self.added_lines,
            "removed_lines": self.removed_lines,
            "churn": self.churn,
            "touches_protected_test": self.touches_protected_test,
            "touches_generated": self.touches_generated,
            "analysable": self.analysable,
            "parses": self.parses,
            "max_complexity": self.max_complexity,
            "max_function_lines": self.max_function_lines,
            "file_lines": self.file_lines,
            "depended_on_by": self.depended_on_by,
            "importance": self.importance,
            "new_dependencies": list(self.new_dependencies),
            "structural": self.structural,
        }


def measure(change: Change, policy: Policy | str | dict | None = None,
            graph=None) -> Signals:
    """Everything decidable about ``change``, in one parse of each side.

    ``graph`` is the repository's import graph, when the caller has one. It is
    optional because building it reads every file; without it the blast-radius
    signals stay ``None`` and the rules that use them simply do not fire.
    """
    resolved = Policy.load(policy)
    before, after = change.before or "", change.after or ""
    added, removed = _churn(before, after)

    analysable = change.path.endswith(".py")
    generated = detect(
        change.path, after or before,
        extra_patterns=resolved.generated.extra_patterns,
    ) is not None

    base = Signals(
        path=change.path,
        added_lines=added,
        removed_lines=removed,
        touches_protected_test=resolved.protects(change.path),
        touches_generated=generated,
        analysable=analysable,
    )
    base = _with_graph(base, graph, change.path)
    if not analysable or change.after is None:
        return base
    return _with_code(base, before, after, change.path)


def _with_graph(base: "Signals", graph, path: str) -> "Signals":
    """Add how much of the repository depends on this file."""
    if graph is None:
        return base
    return Signals(**{
        **_as_kwargs(base),
        "depended_on_by": graph.depends_on_me(path),
        "importance": graph.importance(path),
    })


def _churn(before: str, after: str) -> tuple[int, int]:
    """Lines present on one side only. Not a diff — a bound on one."""
    before_lines = before.splitlines()
    after_lines = after.splitlines()
    shared = _multiset_overlap(before_lines, after_lines)
    return len(after_lines) - shared, len(before_lines) - shared


def _multiset_overlap(left: list[str], right: list[str]) -> int:
    from collections import Counter

    counts = Counter(left) & Counter(right)
    return sum(counts.values())


def _with_code(base: Signals, before: str, after: str, path: str) -> Signals:
    """Add everything that requires the file to parse."""
    module = metrics.measure(after, filename=path)
    if not module.ok:
        return Signals(**{**_as_kwargs(base), "parses": False})

    found = symbols.scan(after, filename=path)
    previous = symbols.scan(before, filename=path) if before else None
    was = metrics.measure(before, filename=path) if before else None
    new_imports = tuple(sorted(
        set(module.imports) - set(was.imports if was and was.ok else ())
    ))

    return Signals(**{
        **_as_kwargs(base),
        "parses": True,
        "max_complexity": max((f.complexity for f in module.functions), default=0),
        "max_function_lines": max((f.lines for f in module.functions), default=0),
        "file_lines": module.code_lines,
        "exported_names": len(found.exports) if found.ok else None,
        "imports": len(module.imports),
        "new_dependencies": new_imports,
        "structural": _is_structural(previous, found, new_imports),
    })


def _is_structural(previous, current, new_imports: tuple[str, ...]) -> bool | None:
    """Did the shape change, or only the text inside it?

    Used to keep a comment or docstring edit away from an expensive model. Errs
    toward True: calling a cosmetic change structural wastes a little money,
    calling a structural one cosmetic routes real work to the wrong place.
    """
    if current is None or not current.ok:
        return None
    if previous is None or not previous.ok:
        return True
    return (
        set(previous.definitions) != set(current.definitions)
        or set(previous.exports) != set(current.exports)
        or bool(new_imports)
    )


def _as_kwargs(signals: Signals) -> dict:
    from dataclasses import asdict

    data = asdict(signals)
    data.pop("extra", None)
    return {**data, "extra": dict(signals.extra)}


def matches_any(patterns, path: str) -> bool:
    return glob.matches_any(patterns, path)


__all__ = ["Change", "Signals", "measure"]
