"""Which rules run for which language, and how their output is folded in.

Split from verify.py because the two change for different reasons: that file
when the shape of a verification changes, this one when a language is added or
a rule family moves. Adding TypeScript put verify.py over the length limit it
enforces on everyone else, which is the tool asking for exactly this.

The asymmetry between the two dispatchers is the point. Python goes through
every rule; TypeScript gets shape and says so. A language whose depth is
partial must record the gap, or a file it examined halfway looks like a file
it examined.
"""

from __future__ import annotations

from dataclasses import dataclass

from .core import boundaries, refactor, structure, swallow, typescript
from .core.contract import EXACT_SUFFIXES


def _fold(result, path: str, findings: list, checked: list, skipped: list) -> None:
    """Fold one rule family's output into the run being assembled.

    A family that reported why it could not look has not checked the file, and
    saying otherwise would let an unexamined path count as examined.
    """
    family, unread = result
    findings.extend(family)
    skipped.extend(unread)
    if not unread:
        checked.append(path)


@dataclass(frozen=True)
class _Source:
    """One file's transition, carried as a unit rather than three arguments."""

    before: str | None
    after: str | None
    path: str


@dataclass(frozen=True)
class _Run:
    """The lists a verification is filling in. Holds references, not copies."""

    findings: list
    checked: list
    skipped: list


def _shape_only(source: _Source, resolved, run: _Run) -> None:
    """Languages that get structural rules and nothing else.

    Shape ran; the assertion rules did not. For an ordinary module that is a
    real examination with a stated gap. For a *protected test file* it is not:
    the one thing that file exists to guarantee was never read, and recording
    it as checked would claim otherwise (RULES.md section 5).
    """
    path = source.path
    shape, unreadable = structure.check(source.before, source.after, path,
                                        resolved.structure)
    run.findings.extend(shape)
    run.skipped.extend(unreadable)
    run.skipped.append(f"{path}: assertions are not analysed in this language")
    if not unreadable and not resolved.protects(path):
        run.checked.append(path)


def _python_rules(source: _Source, resolved, also_defined, run: _Run) -> None:
    """Every rule that needs a Python syntax tree, folded into one run.

    Grouped because they share a precondition and a verdict: if the names pass
    could not read the file, none of the others looked at it either, so the
    path is recorded as examined exactly once for the whole group.
    """
    before, after, path = source.before, source.after, source.path
    names, names_skipped = refactor.check(
        before, after, path,
        on_dangling=resolved.refactor.dangling_reference,
        on_export_removed=resolved.refactor.export_removed,
        also_defined=also_defined or (),
    )
    shape, shape_skipped = structure.check(before, after, path, resolved.structure)
    layers, layers_skipped = boundaries.check(before, after, path, resolved.boundaries)

    run.findings.extend(names + shape + layers)
    run.findings.extend(swallow.check(before, after, path, resolved.refactor))
    run.skipped.extend(names_skipped + shape_skipped + layers_skipped)
    if not names_skipped:
        run.checked.append(path)



def by_language(source: _Source, resolved, also_defined, run: _Run) -> None:
    """Run whichever rule family claims this file, or none.

    A file no branch claims is left entirely alone here; ``verify_change``
    notices that nothing examined it and records the gap. Adding a language
    is a branch, and its depth is whichever helper it points at.
    """
    if source.path.endswith(EXACT_SUFFIXES):
        _python_rules(source, resolved, also_defined, run)
    elif source.path.endswith(typescript.SUFFIXES):
        _shape_only(source, resolved, run)


__all__ = ["_Source", "_Run", "_fold", "by_language"]
