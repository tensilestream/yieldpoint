"""Subject generalisation.

A subject is the expression an assertion constrains — ``invoice.total``,
``calc(2)``. Comparing them literally is right almost always, and wrong for one
important case: parametrisation rewrites the expression without weakening
anything.

    before:  assert calc(1) == 2         after:  @parametrize("n,expected", ...)
             assert calc(2) == 4                 def test_calc(n, expected):
                                                     assert calc(n) == expected

Literal comparison sees ``calc(1)`` and ``calc(2)`` vanish and reports two
weakenings. Both are false. Generalisation replaces literals and parameter names
with a placeholder so the three forms collapse to ``calc(?)`` and match.

``await`` is stripped for the same reason. Making a test asynchronous rewrites
``fetch()`` as ``await fetch()`` without changing one thing about what is
verified, and a suite converting to ``pytest.mark.asyncio`` would otherwise
report every subject in it as lost.

Used only as a *fallback* after exact matching fails, so precision is preserved.
"""

from __future__ import annotations

import ast
from typing import Iterable, Mapping

PLACEHOLDER = "?"


class _Generalizer(ast.NodeTransformer):
    def __init__(self, params: frozenset[str], aliases: dict[str, str] | None = None) -> None:
        self.params = params
        self.aliases = aliases or {}

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        if node.value is None or isinstance(node.value, bool):
            return node  # None/True/False are meaningful, not incidental values
        return ast.Name(id=PLACEHOLDER, ctx=ast.Load())

    def visit_Name(self, node: ast.Name) -> ast.AST:
        if node.id in self.params:
            return ast.Name(id=PLACEHOLDER, ctx=ast.Load())
        bound = self.aliases.get(node.id)
        if bound is not None:
            try:
                return self.visit(ast.parse(bound, mode="eval").body)
            except (SyntaxError, ValueError, RecursionError):
                return node
        return node

    def visit_Await(self, node: ast.Await) -> ast.AST:
        """``await f()`` and ``f()`` name the same subject."""
        return self.visit(node.value)


def generalize(
    expression: str,
    params: Iterable[str] = (),
    aliases: Mapping[str, str] | None = None,
) -> str:
    """Return ``expression`` with literals and ``params`` replaced by ``?``.

    ``aliases`` maps a local name to the expression it was assigned, so that
    renaming a variable does not read as losing the subject it held.

    Falls back to the original text when the expression cannot be re-parsed, so a
    generalisation failure degrades to exact matching rather than to an error.
    """
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, ValueError, RecursionError):
        return expression
    try:
        transformed = _Generalizer(frozenset(params), dict(aliases or {})).visit(tree)
        return ast.unparse(ast.fix_missing_locations(transformed))
    except (ValueError, RecursionError):
        return expression


def aliases_in(body: Iterable[ast.stmt]) -> dict[str, str]:
    """Local names assigned exactly once, mapped to the expression assigned.

    Only single assignments qualify. A name written twice does not stand for one
    expression, and substituting either value would describe a subject the test
    never asserted. Assignments from a bare literal are skipped: turning
    ``total`` into ``5`` makes the subject less recognisable, not more.
    """
    counts: dict[str, int] = {}
    bound: dict[str, str] = {}
    for stmt in body:
        if not isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            continue
        targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
        value = stmt.value
        if value is None or isinstance(value, ast.Constant):
            continue
        for target in targets:
            if not isinstance(target, ast.Name):
                continue
            counts[target.id] = counts.get(target.id, 0) + 1
            bound[target.id] = ast.unparse(value)
    return {
        name: text for name, text in bound.items()
        if counts.get(name) == 1 and not _self_referential(name, text)
    }


def _self_referential(name: str, text: str) -> bool:
    """``x = f(x)`` cannot be substituted without looping."""
    try:
        tree = ast.parse(text, mode="eval")
    except (SyntaxError, ValueError, RecursionError):
        return True
    return any(isinstance(n, ast.Name) and n.id == name for n in ast.walk(tree))
