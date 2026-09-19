"""Whole-object assertions rewritten as per-field assertions.

Splitting one comparison into several is a readability refactor people perform
constantly::

    assert response == {"status": 200, "body": "ok"}

    # becomes
    assert response["status"] == 200
    assert response["body"] == "ok"

Compared subject by subject, ``response`` vanishes and two unrelated subjects
appear, so domination reports a weakening that nobody committed.

The test applied here is exact rather than approximate: the before-assertion's
expected value must be a literal, which names precisely which components were
constrained, and *every one* of them must be asserted at equal strength
afterwards. Drop one field and the finding stands, correctly.

**What this deliberately gives up.** Dict equality also asserts the absence of
keys the literal does not mention; per-field assertions do not. So the rewrite
is a genuine, if narrow, loss of exhaustiveness, and suppressing it is a
judgement, not a proof. It is the right judgement because the legitimate
refactor is common while the exploit is not: dropping the exhaustiveness check
does not turn a failing test green unless the failure was an unexpected extra
key. A team that cares about that case should assert the whole object.
"""

from __future__ import annotations

import ast

from .relation import Relation


def covered(subject: str, expected: str | None, relation: Relation, after) -> bool:
    """True when ``after`` asserts every component ``expected`` pinned.

    ``after`` maps subject expression to the strongest relation asserted on it.
    """
    if relation is not Relation.EQ or not expected:
        return False
    components = decompose(subject, expected)
    if not components:
        return False
    return all(
        after.get(component, Relation.NONE).rank >= relation.rank
        for component in components
    )


def decompose(subject: str, expected: str) -> list[str]:
    """Subject expressions for each component of a literal expected value.

    Empty when the expected value is not a literal whose components are
    statically known — which is the common case, and means no suppression.
    """
    try:
        node = ast.parse(expected, mode="eval").body
    except (SyntaxError, ValueError, RecursionError):
        return []

    if isinstance(node, ast.Dict):
        return _mapping(subject, node)
    if isinstance(node, (ast.List, ast.Tuple)):
        return _sequence(subject, node)
    return []


def _mapping(subject: str, node: ast.Dict) -> list[str]:
    """``{'a': 1}`` against ``resp`` -> ``["resp['a']"]``. Empty if any key is dynamic."""
    if not node.keys or any(k is None for k in node.keys):
        return []  # empty literal constrains nothing; ``**spread`` is not static
    out = []
    for key in node.keys:
        if not isinstance(key, ast.Constant):
            return []
        out.append(f"{subject}[{key.value!r}]")
    return out


def _sequence(subject: str, node: ast.List | ast.Tuple) -> list[str]:
    """A list literal pins each index, and also its length."""
    if not node.elts or any(isinstance(e, ast.Starred) for e in node.elts):
        return []
    return [f"{subject}[{index}]" for index in range(len(node.elts))]


__all__ = ["covered", "decompose"]
