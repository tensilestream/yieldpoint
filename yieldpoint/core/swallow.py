"""A handler that catches everything and records nothing.

The most on-thesis of the rules a field review asked for. Every other
maintainability rule describes shape; this one describes a change in what the
code can still tell you. A broad handler whose body is ``pass`` converts a
failure into a success, so the test that covered the failing path keeps
passing while verifying nothing. That is the same loss this package was built
to report, arriving through the source rather than through the suite.

It is also the cheapest way out of a red test, which is why something under
pressure to make a suite go green reaches for it.

Two discriminators, and both matter more than the rule itself:

**Breadth.** ``except KeyError`` names what was expected, and naming it is the
considered decision. Only ``Exception``, ``BaseException`` and a bare
``except:`` are reported.

**Silence.** A handler that logs, re-raises, or returns a substitute value has
made a choice a reader can see. Only handlers that discard the error with no
trace at all are reported: ``pass``, ``...``, ``continue``, and a bare
``return``.

Differential. A handler that was already there is not this change's doing.
"""

from __future__ import annotations

import ast
from collections import Counter
from dataclasses import dataclass

from .verdict import Confidence, Finding, Status

SWALLOWED_EXCEPTION = "swallowed_exception"

#: Catching one of these catches everything, including the errors nobody
#: predicted — which are exactly the ones worth hearing about.
_BROAD = frozenset({"Exception", "BaseException"})


@dataclass(frozen=True)
class Swallow:
    """One handler that catches broadly and leaves no trace."""

    function: str
    caught: str
    line: int


def _caught(handler: ast.ExceptHandler) -> str:
    """How broadly this handler catches, or empty when it is specific."""
    if handler.type is None:
        return "except:"
    names = [handler.type] if not isinstance(handler.type, ast.Tuple) else handler.type.elts
    for node in names:
        if isinstance(node, ast.Name) and node.id in _BROAD:
            return f"except {node.id}"
    return ""


def _silent(body: list[ast.stmt]) -> bool:
    """Whether the handler leaves no record that anything went wrong."""
    for statement in body:
        if isinstance(statement, (ast.Pass, ast.Continue)):
            continue
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant) \
                and statement.value.value is Ellipsis:
            continue
        if isinstance(statement, ast.Return) and (
                statement.value is None
                or (isinstance(statement.value, ast.Constant)
                    and statement.value.value is None)):
            continue
        return False
    return bool(body)


def _walk(node: ast.AST, prefix: str, out: list[Swallow]) -> None:
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            _walk(child, f"{prefix}{child.name}.", out)
            continue
        if isinstance(child, ast.ExceptHandler):
            caught = _caught(child)
            if caught and _silent(child.body):
                out.append(Swallow(prefix.rstrip("."), caught, child.lineno))
        _walk(child, prefix, out)


def find(source: str | None) -> list[Swallow]:
    """Every broad, silent handler in ``source``. Never raises."""
    if not source:
        return []
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return []
    found: list[Swallow] = []
    _walk(tree, "", found)
    return found


def check(before: str | None, after: str | None, path: str, config) -> list[Finding]:
    """Report handlers this change added. Inherited ones are not its doing.

    Returns findings only. This rule cannot decline to look: a source that does
    not parse yields nothing here and is reported as skipped by the rules that
    share its block, so the file is never recorded as examined on its own.
    """
    severity = getattr(config, "swallowed_exception", config)
    if severity is None or not after:
        return []
    existing = Counter((s.function, s.caught) for s in find(before))
    findings = []
    for swallow in find(after):
        key = (swallow.function, swallow.caught)
        if existing[key]:
            existing[key] -= 1
            continue
        where = f"`{swallow.function}` " if swallow.function else ""
        findings.append(Finding(
            rule=SWALLOWED_EXCEPTION, status=severity, file=path,
            line=swallow.line, symbol=swallow.function or None,
            detail=f"{where}gained `{swallow.caught}` with a handler that does "
                   "nothing. Every failure on this path now looks like success.",
            prescription="Catch the exception you expect by name, or keep the "
                         "broad catch and log or re-raise. A handler that "
                         "records nothing turns a failure into a silent pass.",
            confidence=Confidence.EXACT,
        ))
    return findings


__all__ = ["SWALLOWED_EXCEPTION", "Swallow", "find", "check"]
