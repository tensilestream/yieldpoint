"""Recognising assertions in an AST expression.

Reduces each assertion to ``(subject, relation, expected)`` so that two spellings
of the same check compare equal — a bare ``assert``, a ``unittest`` method and a
``pytest.raises`` block all become the same shape.

Separated from test discovery (assertions.py) because they change for different
reasons: this file grows when a framework adds a spelling, that one when test
layout conventions change.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

from .relation import Relation
from .spellings import (
    ASSERT_CALL_PREFIXES,
    COMPARE_RELATIONS,
    FLUENT_RELATIONS,
    FLUENT_ROOTS,
    MATCHER_RELATIONS,
    METHOD_RELATIONS,
    NEGATIONS,
    fold,
)

@dataclass(frozen=True)
class Assertion:
    """One canonical assertion."""

    subject: str
    relation: Relation
    line: int
    expected: str | None = None
    raw: str = ""
    reachable: bool = True

    @property
    def effective(self) -> Relation:
        """Strength after accounting for reachability.

        An assertion on a dead path, or one whose failure is swallowed by a bare
        ``except``, verifies nothing regardless of how it is written.
        """
        return self.relation if self.reachable else Relation.NONE



def from_assert(stmt: ast.Assert, reachable: bool) -> list[Assertion]:
    raw = ast.unparse(stmt)
    return [
        _classify(part, stmt.lineno, raw, reachable)
        for part in _split_conjunction(stmt.test)
    ]


def _split_conjunction(test: ast.expr) -> list[ast.expr]:
    """``assert a == 1 and b == 2`` is two assertions, and must be counted as two."""
    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.And):
        parts: list[ast.expr] = []
        for value in test.values:
            parts.extend(_split_conjunction(value))
        return parts
    return [test]


def _classify(test: ast.expr, line: int, raw: str, reachable: bool) -> Assertion:
    if isinstance(test, ast.Constant):
        return Assertion(ast.unparse(test), Relation.VACUOUS, line, raw=raw, reachable=reachable)

    if isinstance(test, ast.Compare) and test.comparators:
        return _from_compare(test, line, raw, reachable)

    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        return Assertion(
            ast.unparse(test.operand), Relation.TRUTHY, line, raw=raw, reachable=reachable
        )

    if isinstance(test, ast.Call):
        call = from_call(test, reachable, line=line, raw=raw)
        if call is not None:
            return call

    return Assertion(ast.unparse(test), Relation.TRUTHY, line, raw=raw, reachable=reachable)


def _from_compare(test: ast.Compare, line: int, raw: str, reachable: bool) -> Assertion:
    op = type(test.ops[0])
    right = test.comparators[0]
    relation = COMPARE_RELATIONS.get(op, Relation.COMPARISON)

    # "x is not None" and "x != None" only prove existence; "x is None" is exact.
    if _is_none(right) and op in (ast.IsNot, ast.NotEq):
        relation = Relation.NON_NULL

    subject, expected = test.left, right
    if isinstance(subject, ast.Constant) and not isinstance(right, ast.Constant):
        subject, expected = right, test.left  # normalise "42 == x"

    return Assertion(
        subject=ast.unparse(subject),
        relation=relation,
        line=line,
        expected=ast.unparse(expected),
        raw=raw,
        reachable=reachable,
    )


def _is_none(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def from_call(
    call: ast.Call, reachable: bool, *, line: int | None = None, raw: str = ""
) -> Assertion | None:
    """Recognise every supported assertion spelling.

    Fluent chains are tried first: in `assert_that(x).is_equal_to(y)` the outer
    method carries the relation and the chain's root carries the subject, so
    reading only the outer call name would miss both.
    """
    fluent = _from_fluent(call, reachable, line=line, raw=raw)
    if fluent is not None:
        return fluent

    name = _call_name(call)
    if name is None:
        return None
    lineno = line if line is not None else call.lineno
    text = raw or ast.unparse(call)

    relation = METHOD_RELATIONS.get(name)
    if relation is not None:
        subject = ast.unparse(call.args[0]) if call.args else name
        expected = ast.unparse(call.args[1]) if len(call.args) > 1 else None
        if relation is Relation.RAISES:
            subject, expected = f"{name}({subject})", None
        return Assertion(subject, relation, lineno, expected, text, reachable)

    if name in ("raises", "warns", "deprecated_call"):
        subject = ast.unparse(call.args[0]) if call.args else name
        return Assertion(f"raises({subject})", Relation.RAISES, lineno, None, text, reachable)

    lowered = name.lower()
    if any(lowered.startswith(prefix) for prefix in ASSERT_CALL_PREFIXES):
        # Assertions live inside the helper; strength is unknown, never guessed.
        return Assertion(ast.unparse(call), Relation.OPAQUE, lineno, None, text, reachable)

    return None


def _from_fluent(
    call: ast.Call, reachable: bool, *, line: int | None = None, raw: str = ""
) -> Assertion | None:
    """`assert_that(x).is_equal_to(y)`, `expect(x).to.equal(y)`, `assertThat(x).isEqualTo(y)`."""
    root, links = _chain_root(call)
    if root is None:
        return None

    lineno = line if line is not None else call.lineno
    text = raw or ast.unparse(call)
    subject = ast.unparse(root.args[0]) if root.args else _call_name(root) or "assertion"

    # `assert_that(x, equal_to(y))`: the matcher is the second argument.
    if len(root.args) > 1:
        return _from_matcher(root, subject, lineno, text, reachable)

    relation = _terminal_relation(_call_name(call), links)
    if relation is Relation.EQ and any(fold(link) in NEGATIONS for link in links):
        relation = Relation.COMPARISON  # "not equal to x" bounds rather than pins
    expected = ast.unparse(call.args[0]) if call.args else None
    return Assertion(subject, relation, lineno, expected, text, reachable)


def _terminal_relation(terminal: str | None, links: list[str]) -> Relation:
    """Resolve the relation a chain asserts.

    Chai splits it across links — `expect(x).to.equal(3)` means `to_equal` — so
    the terminal is tried alone first, then with each preceding link folded onto
    it. That covers connector words without enumerating them.
    """
    if not terminal:
        return Relation.OPAQUE
    direct = FLUENT_RELATIONS.get(fold(terminal))
    if direct is not None:
        return direct
    joined = terminal
    for link in links[1:]:
        joined = f"{link}{joined}"
        found = FLUENT_RELATIONS.get(fold(joined))
        if found is not None:
            return found
    return Relation.OPAQUE


def _from_matcher(
    root: ast.Call, subject: str, line: int, raw: str, reachable: bool
) -> Assertion:
    matcher = root.args[1]
    name = _call_name(matcher) if isinstance(matcher, ast.Call) else (
        matcher.id if isinstance(matcher, ast.Name) else ""
    )
    relation = MATCHER_RELATIONS.get(fold(name or ""), Relation.OPAQUE)
    return Assertion(subject, relation, line, ast.unparse(matcher), raw, reachable)


def _chain_root(node: ast.expr) -> tuple[ast.Call | None, list[str]]:
    """Walk a fluent chain back to the call that names its subject.

    Returns the root call and the attribute names passed through, which is how
    a negating link anywhere in the chain is detected.
    """
    links: list[str] = []
    current: ast.expr | None = node
    while isinstance(current, (ast.Call, ast.Attribute)):
        if isinstance(current, ast.Call):
            if isinstance(current.func, ast.Name) and current.func.id in FLUENT_ROOTS:
                return current, links
            current = current.func
        else:
            links.append(current.attr)
            current = current.value
    return None, links


def _call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None
