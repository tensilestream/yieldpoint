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
from dataclasses import dataclass, field

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
    """Measure one module. Never raises."""
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        return ModuleMetrics(error=f"could not parse {filename}: {exc.msg} (line {exc.lineno})")
    except (ValueError, RecursionError) as exc:
        return ModuleMetrics(error=f"could not parse {filename}: {exc}")

    functions: list[FunctionMetrics] = []
    _walk(tree, prefix="", out=functions)

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


def _walk(node: ast.AST, *, prefix: str, out: list[FunctionMetrics]) -> None:
    for child in getattr(node, "body", []):
        if isinstance(child, ast.ClassDef):
            _walk(child, prefix=f"{prefix}{child.name}.", out=out)
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(_function(child, prefix))
            _walk(child, prefix=f"{prefix}{child.name}.", out=out)


def _function(node: ast.FunctionDef | ast.AsyncFunctionDef, prefix: str) -> FunctionMetrics:
    args = node.args
    end = getattr(node, "end_lineno", node.lineno) or node.lineno
    statements = [n for n in ast.walk(node) if isinstance(n, ast.stmt)]
    return FunctionMetrics(
        name=node.name,
        qualname=f"{prefix}{node.name}",
        line=node.lineno,
        lines=max(1, end - node.lineno + 1),
        parameters=(
            len(args.posonlyargs) + len(args.args) + len(args.kwonlyargs)
            + (1 if args.vararg else 0) + (1 if args.kwarg else 0)
        ),
        nesting=_nesting(node),
        complexity=_complexity(node),
        shape=shape_of(node),
        statements=len(statements),
    )


def _nesting(node: ast.AST, depth: int = 0) -> int:
    deepest = depth
    for child in ast.iter_child_nodes(node):
        step = depth + 1 if isinstance(child, _NESTING) else depth
        deepest = max(deepest, _nesting(child, step))
    return deepest


def _complexity(node: ast.AST) -> int:
    """Branch points plus one — the number of independent paths."""
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


def _calls(tree: ast.Module) -> dict[str, int]:
    counts: dict[str, int] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = (
            node.func.id if isinstance(node.func, ast.Name)
            else node.func.attr if isinstance(node.func, ast.Attribute) else None
        )
        if name:
            counts[name] = counts.get(name, 0) + 1
    return counts
