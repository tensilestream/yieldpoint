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

Used only as a *fallback* after exact matching fails, so precision is preserved.
"""

from __future__ import annotations

import ast
from typing import Iterable

PLACEHOLDER = "?"


class _Generalizer(ast.NodeTransformer):
    def __init__(self, params: frozenset[str]) -> None:
        self.params = params

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        if node.value is None or isinstance(node.value, bool):
            return node  # None/True/False are meaningful, not incidental values
        return ast.Name(id=PLACEHOLDER, ctx=ast.Load())

    def visit_Name(self, node: ast.Name) -> ast.AST:
        if node.id in self.params:
            return ast.Name(id=PLACEHOLDER, ctx=ast.Load())
        return node


def generalize(expression: str, params: Iterable[str] = ()) -> str:
    """Return ``expression`` with literals and ``params`` replaced by ``?``.

    Falls back to the original text when the expression cannot be re-parsed, so a
    generalisation failure degrades to exact matching rather than to an error.
    """
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, ValueError, RecursionError):
        return expression
    try:
        transformed = _Generalizer(frozenset(params)).visit(tree)
        return ast.unparse(ast.fix_missing_locations(transformed))
    except (ValueError, RecursionError):
        return expression
