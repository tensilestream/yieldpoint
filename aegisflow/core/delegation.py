"""Assertions a test delegates to a function it calls.

Extracting a shared check into a helper is one of the most common things people
do to a test suite::

    def check_user(u):
        assert u.name == 'alice'
        assert u.age == 30

    def test_user():
        check_user(load())

Reading only functions whose names begin with ``test`` gets this wrong twice,
and the second way is worse than the first:

1. **False positive.** Performing that extraction looks like deleting two
   assertions, because the subjects leave the test body.
2. **False negative.** Once the assertions live in the helper, *weakening the
   helper* is invisible — both states are equally blank, so nothing is reported.
   A suite that already uses helpers, which most mature suites do, is silently
   outside the product's main guarantee.

So a statement-level call to a same-module function that asserts is expanded:
the helper's assertions are attributed to the caller, with its parameters
substituted by the argument expressions at the call site. ``check_user(load())``
contributes ``load().name`` and ``load().age``.

Expansion is symmetric — applied to the before and after state alike — so it
cannot invent a weakening; it can only reveal one that was hidden, or dissolve
one that was never real. Only same-module helpers are visible; an imported one
is left alone rather than guessed at.
"""

from __future__ import annotations

import ast
from dataclasses import replace

#: How far a helper calling a helper is followed. Bounded so a cycle terminates
#: and a deep chain cannot make extraction quadratic.
MAX_DEPTH = 3


def expand(assertions, calls, helpers, depth: int = 0):
    """Return ``assertions`` plus those reached through ``calls``.

    ``calls`` are unparsed statement-level call expressions; ``helpers`` maps a
    function name to its ``(parameters, assertions)``.
    """
    if depth >= MAX_DEPTH or not helpers:
        return assertions

    out = list(assertions)
    for text in calls:
        found = _resolve(text, helpers)
        if found is None:
            continue
        params, inner, inner_calls = found
        bound = _bind(text, params)
        if bound is None:
            continue
        reached = expand(inner, inner_calls, helpers, depth + 1)
        out.extend(
            replace(a, subject=_substitute(a.subject, bound)) for a in reached
        )
    return out


def _resolve(text: str, helpers):
    """The helper a call refers to, or ``None`` if it is not one."""
    node = _parse_call(text)
    if node is None or not isinstance(node.func, ast.Name):
        return None
    return helpers.get(node.func.id)


def _bind(text: str, params) -> dict[str, str] | None:
    """Map each helper parameter to the argument expression at the call site.

    ``None`` when the call cannot be matched to the signature — too many
    arguments, or a ``*args`` spread whose contents are not statically known.
    Refusing to guess keeps an unresolvable call from producing a wrong subject.
    """
    node = _parse_call(text)
    if node is None:
        return None
    if any(isinstance(a, ast.Starred) for a in node.args):
        return None
    if len(node.args) > len(params):
        return None

    bound = {name: ast.unparse(arg) for name, arg in zip(params, node.args)}
    for keyword in node.keywords:
        if keyword.arg is None:  # **kwargs
            return None
        if keyword.arg not in params:
            return None
        bound[keyword.arg] = ast.unparse(keyword.value)
    return bound


def _parse_call(text: str) -> ast.Call | None:
    try:
        node = ast.parse(text, mode="eval").body
    except (SyntaxError, ValueError, RecursionError):
        return None
    return node if isinstance(node, ast.Call) else None


def _substitute(expression: str, bound: dict[str, str]) -> str:
    """Rewrite parameter names in ``expression`` to the caller's arguments."""
    if not bound:
        return expression
    try:
        tree = ast.parse(expression, mode="eval")
        replaced = _Substituter(bound).visit(tree)
        return ast.unparse(ast.fix_missing_locations(replaced))
    except (SyntaxError, ValueError, RecursionError):
        return expression


class _Substituter(ast.NodeTransformer):
    def __init__(self, bound: dict[str, str]) -> None:
        self.bound = bound

    def visit_Name(self, node: ast.Name) -> ast.AST:
        argument = self.bound.get(node.id)
        if argument is None:
            return node
        try:
            return ast.parse(argument, mode="eval").body
        except (SyntaxError, ValueError, RecursionError):
            return node


__all__ = ["expand", "MAX_DEPTH"]
