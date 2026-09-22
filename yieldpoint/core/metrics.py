"""Structural measurements of a module.

Pure counting, no judgement: thresholds and severities live in policy, and the
rules that apply them live in structure.py. Splitting it this way means a team
can retune limits without touching analysis, and a new rule can reuse a
measurement that already exists.

Everything here is deterministic — the same source always yields the same
numbers, with no clock, environment or randomness (RULES.md section 4).
"""

from __future__ import annotations

import ast
import hashlib
from dataclasses import asdict, dataclass, field

#: Statements that open a nesting level.
_NESTING = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try)

#: Nodes that add a branch, and therefore a path through the code.
_BRANCHES = (
    ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler,
    ast.IfExp, ast.Assert, ast.comprehension,
)


@dataclass(frozen=True)
class FunctionMetrics:
    """One function, measured."""

    name: str
    qualname: str
    line: int
    lines: int
    parameters: int
    nesting: int
    complexity: int
    shape: str
    statements: int

    @property
    def substantial(self) -> bool:
        """Big enough that duplication is meaningful rather than coincidental."""
        return self.statements >= 5


@dataclass(frozen=True)
class ModuleMetrics:
    """One module, measured. ``error`` set means nothing could be measured."""

    lines: int = 0
    code_lines: int = 0
    definitions: int = 0
    functions: tuple[FunctionMetrics, ...] = ()
    imports: tuple[str, ...] = ()
    calls: dict[str, int] = field(default_factory=dict)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def measure(source: str, *, filename: str = "<source>") -> ModuleMetrics:
    """Measure one module. Never raises.

    Cached by a hash of the source. Measuring costs about four times what
    parsing does, and most of what any run measures is a file unchanged since
    the last one. ``filename`` is deliberately not part of the key: it appears
    only in an error message, and keying on it would miss every renamed or
    replayed file (see parsecache.py).
    """
    from .parsecache import Codec, through
    from .typescript import SUFFIXES, measure as _typescript

    # The language is part of the cache kind, not only the computation: the
    # key is a hash of the source and `filename` is deliberately excluded from
    # it, so without this a file of valid-in-both syntax would serve one
    # language's measurements to the other.
    if filename.endswith(SUFFIXES):
        return through(
            source, Codec("metrics-ts", _encode, _decode),
            compute=lambda: _typescript(source, filename=filename),
        )
    return through(
        source, Codec("metrics", _encode, _decode),
        compute=lambda: _measure(source, filename),
    )


def _encode(module: "ModuleMetrics") -> dict:
    return {
        "lines": module.lines, "code_lines": module.code_lines,
        "definitions": module.definitions, "imports": list(module.imports),
        "calls": module.calls, "error": module.error,
        "functions": [asdict(f) for f in module.functions],
    }


def _decode(payload: dict) -> "ModuleMetrics":
    return ModuleMetrics(
        lines=payload["lines"], code_lines=payload["code_lines"],
        definitions=payload["definitions"], imports=tuple(payload["imports"]),
        calls=dict(payload["calls"]), error=payload["error"],
        functions=tuple(FunctionMetrics(**f) for f in payload["functions"]),
    )


def _measure(source: str, filename: str) -> ModuleMetrics:
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        return ModuleMetrics(error=f"could not parse {filename}: {exc.msg} (line {exc.lineno})")
    except (ValueError, RecursionError) as exc:
        return ModuleMetrics(error=f"could not parse {filename}: {exc}")

    functions: list[FunctionMetrics] = []
    _walk(tree, prefix="", out=functions, annotations=_annotations(source))

    return ModuleMetrics(
        lines=len(source.splitlines()),
        code_lines=_code_lines(source),
        definitions=sum(
            1 for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        ),
        functions=tuple(functions),
        imports=tuple(_imports(tree)),
        calls=_calls(tree),
    )


def _code_lines(source: str) -> int:
    """Lines excluding blanks and comment-only lines — the RULES.md section 1 count."""
    total = 0
    for line in source.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            total += 1
    return total


def _annotations(source: str) -> frozenset[int]:
    """Lines that exist only to carry one of Yieldpoint's own acknowledgements.

    Discounted from a function's length, because the alternative is a tool that
    lengthens a function as the price of admitting the length was intended.
    Worse than merely absurd: a comment written to answer *one* rule would push
    an unrelated length rule over its limit, so the escape hatch manufactures
    the finding it was used to answer.

    Only whole-line comments count. An acknowledgement appended to a statement
    rides on a line that would have existed anyway, so discounting it would
    undercount real code.
    """
    from .acknowledge import scan

    lines = source.splitlines()
    return frozenset(number for number in scan(source)
                     if lines[number - 1].strip().startswith("#"))


def _walk(node: ast.AST, *, prefix: str, out: list[FunctionMetrics],
          annotations: frozenset[int]) -> None:
    for child in getattr(node, "body", []):
        if isinstance(child, ast.ClassDef):
            _walk(child, prefix=f"{prefix}{child.name}.", out=out,
                  annotations=annotations)
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(_function(child, prefix, annotations))
            _walk(child, prefix=f"{prefix}{child.name}.", out=out,
                  annotations=annotations)


def _function(node: ast.FunctionDef | ast.AsyncFunctionDef, prefix: str,
              annotations: frozenset[int] = frozenset()) -> FunctionMetrics:
    args = node.args
    end = getattr(node, "end_lineno", node.lineno) or node.lineno
    statements, nesting, complexity = _survey(node)
    excused = sum(1 for number in annotations if node.lineno <= number <= end)
    return FunctionMetrics(
        name=node.name,
        qualname=f"{prefix}{node.name}",
        line=node.lineno,
        lines=max(1, end - node.lineno + 1 - excused),
        parameters=(
            len(args.posonlyargs) + len(args.args) + len(args.kwonlyargs)
            + (1 if args.vararg else 0) + (1 if args.kwarg else 0)
        ),
        nesting=nesting,
        complexity=complexity,
        shape=shape_of(node),
        statements=statements,
    )


def _deeper(parent: ast.AST, child: ast.AST) -> int:
    """Whether stepping to ``child`` goes a level in, as a reader would count it.

    ``elif`` is the exception, and it matters. Python has no elif node: it is an
    ``If`` sitting alone in the previous ``If``'s ``orelse``, so a flat
    four-branch chain measured as four levels of nesting. Nobody reads it that
    way — it is one decision with four answers, and reporting it as deeply
    nested sends people to restructure code that was already flat.
    """
    if not isinstance(child, _NESTING):
        return 0
    if (isinstance(parent, ast.If) and isinstance(child, ast.If)
            and parent.orelse == [child]
            and child.col_offset == parent.col_offset):
        # The column is the only thing separating `elif` from `else:` followed
        # by an `if`: the two are the same tree. The second is indented, and is
        # a real level — the author wrote it as one.
        return 0
    return 1


def _survey(node: ast.AST) -> tuple[int, int, int]:
    """Statements, deepest nesting and complexity, in a single descent.

    These were three traversals of the same subtree, and ``ast.walk`` builds a
    deque on every call. On a two-hundred test file that was most of the time
    spent verifying it. One pass, same numbers — asserted against the old
    implementations in the tests.
    """
    statements = 0
    deepest = 0
    branches = 0

    stack = [(node, 0)]
    while stack:
        current, depth = stack.pop()
        if isinstance(current, ast.stmt):
            statements += 1
        if depth > deepest:
            deepest = depth
        if isinstance(current, _BRANCHES):
            branches += 1
        elif isinstance(current, ast.BoolOp):
            branches += len(current.values) - 1
        elif isinstance(current, ast.match_case):
            branches += 1
        for child in ast.iter_child_nodes(current):
            stack.append((child, depth + _deeper(current, child)))

    return statements, deepest, branches + 1


def _nesting(node: ast.AST, depth: int = 0) -> int:
    """Deepest nesting. Kept as the reference the fast path is tested against."""
    deepest = depth
    for child in ast.iter_child_nodes(node):
        step = depth + 1 if isinstance(child, _NESTING) else depth
        deepest = max(deepest, _nesting(child, step))
    return deepest


def _complexity(node: ast.AST) -> int:
    """Branch points plus one. Kept as the reference for ``_survey``."""
    total = 1
    for child in ast.walk(node):
        if isinstance(child, _BRANCHES):
            total += 1
        elif isinstance(child, ast.BoolOp):
            total += len(child.values) - 1
        elif isinstance(child, ast.match_case):
            total += 1
    return total


def shape_of(node: ast.AST) -> str:
    """A fingerprint of structure with identifiers erased.

    Two functions that differ only in naming produce the same shape, which is
    what makes copy-paste detectable without comparing text.
    """
    digest = hashlib.blake2b(digest_size=12)
    for child in ast.walk(node):
        digest.update(type(child).__name__.encode())
        if isinstance(child, ast.Constant) and isinstance(child.value, (int, float, str, bool)):
            digest.update(b"const")
    return digest.hexdigest()


def _imports(tree: ast.Module) -> list[str]:
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append(node.module)
    return found


def _dotted(func: ast.expr) -> list[str]:
    """Every spelling a caller might forbid, for one call.

    ``os.getenv(...)`` is recorded as both ``getenv`` and ``os.getenv``. Only
    the bare attribute was recorded before, so a project writing
    ``"forbid_call": "os.getenv"`` — the obvious spelling, and the one any
    reader would choose — configured a rule that could never match and was
    told nothing. A rule that is on and silent is worse than one that is off.
    """
    if isinstance(func, ast.Name):
        return [func.id]
    if not isinstance(func, ast.Attribute):
        return []
    names = [func.attr]
    if isinstance(func.value, ast.Name):
        names.append(f"{func.value.id}.{func.attr}")
    elif isinstance(func.value, ast.Attribute) and isinstance(func.value.value, ast.Name):
        names.append(f"{func.value.value.id}.{func.value.attr}.{func.attr}")
    return names


def _calls(tree: ast.Module) -> dict[str, int]:
    counts: dict[str, int] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for name in _dotted(node.func):
            counts[name] = counts.get(name, 0) + 1
    return counts
