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
from dataclasses import dataclass, field, replace

from .delegation import MAX_DEPTH, expand
from .recognise import Assertion, from_assert, from_call
from .relation import Relation
from .subject import aliases_in

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

    aliases: tuple[tuple[str, str], ...] = ()
    """Local names assigned exactly once, paired with the expression assigned.
    Lets a renamed variable resolve to the same subject (see subject.py)."""

    statement_calls: tuple[str, ...] = ()
    """Every statement-level call, recognised or not. A call to a same-module
    helper usually *is* recognised — as an opaque assertion — so helper
    expansion cannot be driven from ``unclassified_calls`` alone."""

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

    helpers = _helpers(tree)
    tests = tuple(
        _with_helpers(case, helpers) for case in _collect(tree, prefix="")
    )
    return Extraction(tests=tests, by_name={t.qualname: t for t in tests})


def _helpers(tree: ast.AST) -> dict[str, tuple]:
    """Same-module functions that assert and are not themselves tests.

    Keyed by bare name because that is what a call site says. A class method is
    excluded: ``self.check(x)`` is not an ``ast.Name`` call, so it would never be
    resolved anyway, and pretending otherwise would bind the wrong parameters.
    """
    found: dict[str, tuple] = {}
    for node in getattr(tree, "body", []):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if _is_test(node.name, prefix=""):
            continue
        sink = _Sink([], [], [])
        _scan(node.body, sink, reachable=True)
        found[node.name] = (
            tuple(_signature(node)), tuple(sink.assertions), tuple(sink.calls)
        )
    return _asserting(found)


def _asserting(candidates: dict[str, tuple]) -> dict[str, tuple]:
    """Keep only functions that assert, directly or through another helper.

    A function that merely calls one is still on the path from the test to the
    assertion, so omitting it breaks the chain: ``test -> row_ok -> field_ok``
    would leave ``field_ok`` unreachable and its weakening unreported. Grown to
    a fixed point rather than in one pass, bounded by the same depth the
    expansion itself honours.
    """
    kept = {name: value for name, value in candidates.items() if value[1]}
    for _ in range(MAX_DEPTH):
        grown = {
            name: value for name, value in candidates.items()
            if name not in kept
            and any(_calls_helper(call, kept) for call in value[2])
        }
        if not grown:
            break
        kept.update(grown)
    return kept


def _signature(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    args = fn.args
    return [a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)]


def _with_helpers(case: TestCase, helpers: dict[str, tuple]) -> TestCase:
    """Attribute helper assertions to the test that calls the helper."""
    if not helpers or not case.statement_calls:
        return case
    resolved = {t for t in case.statement_calls if _calls_helper(t, helpers)}
    if not resolved:
        return case

    # The call itself was recorded as an opaque assertion standing in for
    # whatever it checks. Now that the helper has been read, the stand-in is
    # replaced by the real assertions rather than counted alongside them.
    kept = [a for a in case.assertions if a.subject not in resolved]
    expanded = expand(kept, sorted(resolved), helpers)
    return replace(
        case,
        assertions=tuple(expanded),
        unclassified_calls=tuple(c for c in case.unclassified_calls if c not in resolved),
    )


def _calls_helper(text: str, helpers: dict[str, tuple]) -> bool:
    try:
        node = ast.parse(text, mode="eval").body
    except (SyntaxError, ValueError, RecursionError):
        return False
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
        and node.func.id in helpers


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
    sink = _Sink([], [], [])
    _scan(fn.body, sink, reachable=True)
    body = _significant(fn.body)
    return TestCase(
        qualname=f"{prefix}{fn.name}",
        line=fn.lineno,
        assertions=tuple(sink.assertions),
        skip_markers=tuple(_skip_markers(fn)),
        params=tuple(_params(fn)),
        is_empty=not body,
        body_hash=_body_hash(fn),
        unclassified_calls=tuple(sink.unclassified),
        statement_calls=tuple(sink.calls),
        aliases=tuple(sorted(aliases_in(fn.body).items())),
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


@dataclass
class _Sink:
    """Where a statement walk puts what it finds.

    One object rather than three out-parameters: the walk is recursive and
    threading each list through every branch is how a signature grows past the
    limit this project enforces on everyone else.
    """

    assertions: list
    unclassified: list
    calls: list


def _scan(body: list[ast.stmt], sink: _Sink, *, reachable: bool) -> None:
    """Walk statements, tracking whether an assertion here could actually fail."""
    live = reachable
    for stmt in body:
        _scan_stmt(stmt, sink, reachable=live)
        if isinstance(stmt, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
            live = False


def _scan_stmt(stmt: ast.stmt, sink: _Sink, *, reachable: bool) -> None:
    if isinstance(stmt, ast.Assert):
        sink.assertions.extend(from_assert(stmt, reachable))
        return
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
        _scan_call(stmt.value, sink, reachable=reachable)
        return
    if isinstance(stmt, ast.If):
        branch = _constant_truth(stmt.test)
        _scan(stmt.body, sink, reachable=reachable and branch is not False)
        _scan(stmt.orelse, sink, reachable=reachable and branch is not True)
        return
    if isinstance(stmt, ast.Try):
        # A handler that swallows means assertions in the body cannot fail the test.
        swallowed = any(not _significant(h.body) for h in stmt.handlers)
        _scan(stmt.body, sink, reachable=reachable and not swallowed)
        for handler in stmt.handlers:
            _scan(handler.body, sink, reachable=reachable)
        _scan(stmt.orelse, sink, reachable=reachable)
        _scan(stmt.finalbody, sink, reachable=reachable)
        return
    if isinstance(stmt, (ast.With, ast.AsyncWith)):
        for item in stmt.items:
            if isinstance(item.context_expr, ast.Call):
                found = from_call(item.context_expr, reachable)
                if found and found.relation is Relation.RAISES:
                    sink.assertions.append(found)
        _scan(stmt.body, sink, reachable=reachable)
        return
    if isinstance(stmt, (ast.For, ast.AsyncFor, ast.While)):
        _scan(stmt.body, sink, reachable=reachable)
        _scan(stmt.orelse, sink, reachable=reachable)
        return
    for inner in getattr(stmt, "body", []) or []:
        _scan_stmt(inner, sink, reachable=reachable)


def _scan_call(call: ast.Call, sink: _Sink, *, reachable: bool) -> None:
    """Record a statement-level call as an assertion, a helper call, or both."""
    sink.calls.append(ast.unparse(call))
    found = from_call(call, reachable)
    if found:
        sink.assertions.append(found)
    else:
        sink.unclassified.append(ast.unparse(call))


def _constant_truth(test: ast.expr) -> bool | None:
    """``True``/``False`` for a literal condition, ``None`` when it is dynamic."""
    if isinstance(test, ast.Constant):
        return bool(test.value)
    return None


__all__ = ["Assertion", "TestCase", "Extraction", "extract"]
