"""Finding tests and deciding which of their assertions can actually fail.

Extraction is exact: it parses with :mod:`ast` rather than matching patterns, and
a file it cannot parse is reported as skipped rather than silently passed
(RULES.md section 5).

Reachability is the part that is easy to miss. An assertion inside ``if False``,
after a ``return``, or wrapped in a swallowing ``try/except`` is present in the
source and verifies nothing, so it carries an *effective* strength of ``NONE``.

Assertion recognition itself lives in recognise.py.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field

from .recognise import Assertion, from_assert, from_call
from .relation import Relation

_SKIP_MARKERS = ("skip", "xfail", "skipif", "skipunless", "expectedfailure")


@dataclass(frozen=True)
class TestCase:
    """One test function and everything the checks need to know about it."""

    qualname: str
    line: int
    assertions: tuple[Assertion, ...] = ()
    skip_markers: tuple[str, ...] = ()
    params: tuple[str, ...] = ()
    is_empty: bool = False
    body_hash: str = ""
    unclassified_calls: tuple[str, ...] = ()
    """Statement-level calls no recogniser understood. A test full of these is
    not a test that asserts nothing — it is a style we do not read yet."""

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
    unclassified: list[str] = []
    _scan(fn.body, assertions, reachable=True, unclassified=unclassified)
    body = _significant(fn.body)
    return TestCase(
        qualname=f"{prefix}{fn.name}",
        line=fn.lineno,
        assertions=tuple(assertions),
        skip_markers=tuple(_skip_markers(fn)),
        params=tuple(_params(fn)),
        is_empty=not body,
        body_hash=_body_hash(fn),
        unclassified_calls=tuple(unclassified),
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


def _params(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """Parameter names introduced by ``@pytest.mark.parametrize``.

    Needed so a parametrised rewrite is recognised as equivalent rather than as
    the disappearance of every literal subject it replaced (see subject.py).
    """
    names: list[str] = []
    for decorator in fn.decorator_list:
        if not isinstance(decorator, ast.Call) or not decorator.args:
            continue
        if "parametrize" not in ast.unparse(decorator.func):
            continue
        spec = decorator.args[0]
        if isinstance(spec, ast.Constant) and isinstance(spec.value, str):
            names.extend(part.strip() for part in spec.value.split(",") if part.strip())
        elif isinstance(spec, (ast.List, ast.Tuple)):
            names.extend(
                item.value for item in spec.elts
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            )
    return names


def _body_hash(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Structure-only fingerprint, used to pair renamed tests."""
    return "|".join(type(n).__name__ for n in ast.walk(fn) if isinstance(n, ast.stmt))


# -------------------------------------------------------------- reachability


def _scan(
    body: list[ast.stmt], out: list[Assertion], *, reachable: bool,
    unclassified: list[str] | None = None,
) -> None:
    """Walk statements, tracking whether an assertion here could actually fail."""
    live = reachable
    for stmt in body:
        _scan_stmt(stmt, out, reachable=live, unclassified=unclassified)
        if isinstance(stmt, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
            live = False


def _scan_stmt(
    stmt: ast.stmt, out: list[Assertion], *, reachable: bool,
    unclassified: list[str] | None = None,
) -> None:
    if isinstance(stmt, ast.Assert):
        out.extend(from_assert(stmt, reachable))
        return
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
        found = from_call(stmt.value, reachable)
        if found:
            out.append(found)
        elif unclassified is not None:
            unclassified.append(ast.unparse(stmt.value))
        return
    if isinstance(stmt, ast.If):
        branch = _constant_truth(stmt.test)
        _scan(stmt.body, out, unclassified=unclassified, reachable=reachable and branch is not False)
        _scan(stmt.orelse, out, unclassified=unclassified, reachable=reachable and branch is not True)
        return
    if isinstance(stmt, ast.Try):
        # A handler that swallows means assertions in the body cannot fail the test.
        swallowed = any(not _significant(h.body) for h in stmt.handlers)
        _scan(stmt.body, out, unclassified=unclassified, reachable=reachable and not swallowed)
        for handler in stmt.handlers:
            _scan(handler.body, out, unclassified=unclassified, reachable=reachable)
        _scan(stmt.orelse, out, unclassified=unclassified, reachable=reachable)
        _scan(stmt.finalbody, out, unclassified=unclassified, reachable=reachable)
        return
    if isinstance(stmt, (ast.With, ast.AsyncWith)):
        for item in stmt.items:
            if isinstance(item.context_expr, ast.Call):
                found = from_call(item.context_expr, reachable)
                if found and found.relation is Relation.RAISES:
                    out.append(found)
        _scan(stmt.body, out, unclassified=unclassified, reachable=reachable)
        return
    if isinstance(stmt, (ast.For, ast.AsyncFor, ast.While)):
        _scan(stmt.body, out, unclassified=unclassified, reachable=reachable)
        _scan(stmt.orelse, out, unclassified=unclassified, reachable=reachable)
        return
    for inner in getattr(stmt, "body", []) or []:
        _scan_stmt(inner, out, reachable=reachable, unclassified=unclassified)


def _constant_truth(test: ast.expr) -> bool | None:
    """``True``/``False`` for a literal condition, ``None`` when it is dynamic."""
    if isinstance(test, ast.Constant):
        return bool(test.value)
    return None


__all__ = ["Assertion", "TestCase", "Extraction", "extract"]
