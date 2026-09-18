"""Extract canonical assertions from Python test source.

An assertion is reduced to ``(subject, relation, expected)`` so that two spellings
of the same check compare equal, and so that a rewritten test can still be
compared against its predecessor. Extraction is exact: it parses with :mod:`ast`
rather than matching patterns, and a file it cannot parse is reported as skipped
rather than silently passed (RULES.md section 5).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field

from .relation import Relation

# unittest/pytest method name -> the relation it asserts.
_METHOD_RELATIONS: dict[str, Relation] = {
    "assertEqual": Relation.EQ, "assertEquals": Relation.EQ,
    "assertAlmostEqual": Relation.EQ, "assertIs": Relation.EQ,
    "assertIsNone": Relation.EQ, "assertDictEqual": Relation.EQ,
    "assertListEqual": Relation.EQ, "assertSetEqual": Relation.EQ,
    "assertTupleEqual": Relation.EQ, "assertMultiLineEqual": Relation.EQ,
    "assertCountEqual": Relation.EQ, "assertSequenceEqual": Relation.EQ,
    "assertNotEqual": Relation.COMPARISON, "assertIsNot": Relation.COMPARISON,
    "assertGreater": Relation.COMPARISON, "assertGreaterEqual": Relation.COMPARISON,
    "assertLess": Relation.COMPARISON, "assertLessEqual": Relation.COMPARISON,
    "assertRegex": Relation.COMPARISON, "assertNotAlmostEqual": Relation.COMPARISON,
    "assertIn": Relation.MEMBERSHIP, "assertNotIn": Relation.MEMBERSHIP,
    "assertIsInstance": Relation.MEMBERSHIP, "assertNotIsInstance": Relation.MEMBERSHIP,
    "assertRaises": Relation.RAISES, "assertRaisesRegex": Relation.RAISES,
    "assertWarns": Relation.RAISES, "assertLogs": Relation.RAISES,
    "assertTrue": Relation.TRUTHY, "assertFalse": Relation.TRUTHY,
    "assertIsNotNone": Relation.NON_NULL,
}

_COMPARE_RELATIONS: dict[type[ast.cmpop], Relation] = {
    ast.Eq: Relation.EQ, ast.Is: Relation.EQ,
    ast.NotEq: Relation.COMPARISON, ast.IsNot: Relation.COMPARISON,
    ast.Lt: Relation.COMPARISON, ast.LtE: Relation.COMPARISON,
    ast.Gt: Relation.COMPARISON, ast.GtE: Relation.COMPARISON,
    ast.In: Relation.MEMBERSHIP, ast.NotIn: Relation.MEMBERSHIP,
}

_ASSERT_CALL_PREFIXES = ("assert", "check", "verify", "expect", "should")
_SKIP_MARKERS = ("skip", "xfail", "skipif", "skipunless", "expectedfailure")


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


@dataclass(frozen=True)
class TestCase:
    """One test function and everything the checks need to know about it."""

    qualname: str
    line: int
    assertions: tuple[Assertion, ...] = ()
    skip_markers: tuple[str, ...] = ()
    is_empty: bool = False
    body_hash: str = ""

    @property
    def subjects(self) -> dict[str, Relation]:
        """Strongest *effective* relation per subject — the monotonicity input."""
        strongest: dict[str, Relation] = {}
        for assertion in self.assertions:
            current = strongest.get(assertion.subject)
            if current is None or assertion.effective.rank > current.rank:
                strongest[assertion.subject] = assertion.effective
        return strongest


@dataclass(frozen=True)
class Extraction:
    """Result of extracting one file. ``error`` set means nothing was checked."""

    tests: tuple[TestCase, ...] = ()
    error: str | None = None
    by_name: dict[str, TestCase] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.error is None


def extract(source: str, *, filename: str = "<source>") -> Extraction:
    """Parse ``source`` and return its test cases.

    Never raises on bad input: a syntax error yields an :class:`Extraction` with
    ``error`` set, so the caller records the file as skipped.
    """
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        return Extraction(error=f"could not parse {filename}: {exc.msg} (line {exc.lineno})")
    except (ValueError, RecursionError) as exc:  # null bytes, pathological nesting
        return Extraction(error=f"could not parse {filename}: {exc}")

    tests = tuple(_collect(tree, prefix=""))
    return Extraction(tests=tests, by_name={t.qualname: t for t in tests})


# ------------------------------------------------------------------ collection


def _collect(node: ast.AST, prefix: str):
    """Yield test cases from a module or class body."""
    for child in getattr(node, "body", []):
        if isinstance(child, ast.ClassDef):
            yield from _collect(child, prefix=f"{prefix}{child.name}.")
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _is_test(child.name, prefix):
                yield _build_case(child, prefix)


def _is_test(name: str, prefix: str) -> bool:
    return name.startswith("test") or (bool(prefix) and name.startswith("test"))


def _build_case(fn: ast.FunctionDef | ast.AsyncFunctionDef, prefix: str) -> TestCase:
    assertions: list[Assertion] = []
    _scan(fn.body, assertions, reachable=True)
    body = _significant(fn.body)
    return TestCase(
        qualname=f"{prefix}{fn.name}",
        line=fn.lineno,
        assertions=tuple(assertions),
        skip_markers=tuple(_skip_markers(fn)),
        is_empty=not body,
        body_hash=_body_hash(fn),
    )


def _significant(body: list[ast.stmt]) -> list[ast.stmt]:
    """Body statements excluding the docstring and bare ``pass``/``...``."""
    out = []
    for index, stmt in enumerate(body):
        if isinstance(stmt, ast.Pass):
            continue
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            if index == 0 and isinstance(stmt.value.value, str):
                continue  # docstring
            if stmt.value.value is Ellipsis:
                continue
        out.append(stmt)
    return out


def _skip_markers(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    found = []
    for decorator in fn.decorator_list:
        text = ast.unparse(decorator)
        if any(marker in text.lower() for marker in _SKIP_MARKERS):
            found.append(text)
    return found


def _body_hash(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Structure-only fingerprint, used to pair renamed tests."""
    return "|".join(type(n).__name__ for n in ast.walk(fn) if isinstance(n, ast.stmt))


# -------------------------------------------------------------- reachability


def _scan(body: list[ast.stmt], out: list[Assertion], *, reachable: bool) -> None:
    """Walk statements, tracking whether an assertion here could actually fail."""
    live = reachable
    for stmt in body:
        _scan_stmt(stmt, out, reachable=live)
        if isinstance(stmt, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
            live = False


def _scan_stmt(stmt: ast.stmt, out: list[Assertion], *, reachable: bool) -> None:
    if isinstance(stmt, ast.Assert):
        out.extend(_from_assert(stmt, reachable))
        return
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
        found = _from_call(stmt.value, reachable)
        if found:
            out.append(found)
        return
    if isinstance(stmt, ast.If):
        branch = _constant_truth(stmt.test)
        _scan(stmt.body, out, reachable=reachable and branch is not False)
        _scan(stmt.orelse, out, reachable=reachable and branch is not True)
        return
    if isinstance(stmt, ast.Try):
        # A handler that swallows means assertions in the body cannot fail the test.
        swallowed = any(not _significant(h.body) for h in stmt.handlers)
        _scan(stmt.body, out, reachable=reachable and not swallowed)
        for handler in stmt.handlers:
            _scan(handler.body, out, reachable=reachable)
        _scan(stmt.orelse, out, reachable=reachable)
        _scan(stmt.finalbody, out, reachable=reachable)
        return
    if isinstance(stmt, (ast.With, ast.AsyncWith)):
        for item in stmt.items:
            if isinstance(item.context_expr, ast.Call):
                found = _from_call(item.context_expr, reachable)
                if found and found.relation is Relation.RAISES:
                    out.append(found)
        _scan(stmt.body, out, reachable=reachable)
        return
    if isinstance(stmt, (ast.For, ast.AsyncFor, ast.While)):
        _scan(stmt.body, out, reachable=reachable)
        _scan(stmt.orelse, out, reachable=reachable)
        return
    for inner in getattr(stmt, "body", []) or []:
        _scan_stmt(inner, out, reachable=reachable)


def _constant_truth(test: ast.expr) -> bool | None:
    """``True``/``False`` for a literal condition, ``None`` when it is dynamic."""
    if isinstance(test, ast.Constant):
        return bool(test.value)
    return None


# -------------------------------------------------------------- recognisers


def _from_assert(stmt: ast.Assert, reachable: bool) -> list[Assertion]:
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
        call = _from_call(test, reachable, line=line, raw=raw)
        if call is not None:
            return call

    return Assertion(ast.unparse(test), Relation.TRUTHY, line, raw=raw, reachable=reachable)


def _from_compare(test: ast.Compare, line: int, raw: str, reachable: bool) -> Assertion:
    op = type(test.ops[0])
    right = test.comparators[0]
    relation = _COMPARE_RELATIONS.get(op, Relation.COMPARISON)

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


def _from_call(
    call: ast.Call, reachable: bool, *, line: int | None = None, raw: str = ""
) -> Assertion | None:
    """Recognise ``self.assertX(...)``, ``pytest.raises(...)`` and helper calls."""
    name = _call_name(call)
    if name is None:
        return None
    lineno = line if line is not None else call.lineno
    text = raw or ast.unparse(call)

    relation = _METHOD_RELATIONS.get(name)
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
    if any(lowered.startswith(prefix) for prefix in _ASSERT_CALL_PREFIXES):
        # Assertions live inside the helper; strength is unknown, never guessed.
        return Assertion(ast.unparse(call), Relation.OPAQUE, lineno, None, text, reachable)

    return None


def _call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None
