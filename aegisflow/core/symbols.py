"""Which names a module defines, and which it uses.

A refactor — extracting a module, converting classes to functions, renaming —
breaks in a way test tampering does not: a definition moves or is renamed and a
call site is left pointing at a name that no longer exists. The code still
parses. It fails at run time, or not until the one path that reaches it runs.

Bindings are deliberately **over-approximated**: every name bound anywhere in the
module counts, including inside other functions. A local in one function
therefore masks a genuine problem in another. That direction is chosen on
purpose — it yields false negatives rather than false positives, and a refactor
checker that cries wolf is one nobody runs.
"""

from __future__ import annotations

import ast
import builtins
from dataclasses import dataclass, field

_BUILTINS = frozenset(dir(builtins)) | {
    "__name__", "__file__", "__doc__", "__all__", "__package__", "__spec__",
    "__loader__", "__builtins__", "__debug__", "__path__", "__version__",
}


@dataclass(frozen=True)
class Symbols:
    """What one module binds, loads and exports."""

    bound: frozenset[str] = frozenset()
    loaded: frozenset[str] = frozenset()
    definitions: tuple[str, ...] = ()
    exports: tuple[str, ...] = ()
    star_import: bool = False
    error: str | None = None
    lines: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.error is None

    def dangling(self) -> tuple[str, ...]:
        """Names used here that nothing in this module binds.

        Empty when the module uses ``import *``, because then anything could be
        in scope and a confident answer is not available.
        """
        if not self.ok or self.star_import:
            return ()
        return tuple(sorted(self.loaded - self.bound - _BUILTINS))


def scan(source: str, *, filename: str = "<source>") -> Symbols:
    """Collect the name information for one module. Never raises.

    Cached by a hash of the source, like the other analysers: walking a module
    for every name it binds and loads is the second largest cost in a scan
    after parsing, and both are avoided entirely on a file that has not
    changed. See parsecache.py — and note that ``filename`` is excluded from
    the key on purpose, so a renamed file is still a hit.
    """
    from .parsecache import Codec, through

    return through(
        source, Codec("symbols", _encode, _decode),
        compute=lambda: _scan(source, filename),
    )


def _encode(found: "Symbols") -> dict:
    return {
        "bound": sorted(found.bound),
        "loaded": sorted(found.loaded),
        "definitions": list(found.definitions),
        "exports": list(found.exports),
        "star_import": found.star_import,
        "error": found.error,
        "lines": found.lines,
    }


def _decode(payload: dict) -> "Symbols":
    return Symbols(
        bound=frozenset(payload["bound"]),
        loaded=frozenset(payload["loaded"]),
        definitions=tuple(payload["definitions"]),
        exports=tuple(payload["exports"]),
        star_import=payload["star_import"],
        error=payload["error"],
        lines=dict(payload["lines"]),
    )


def _scan(source: str, filename: str) -> Symbols:
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        return Symbols(error=f"could not parse {filename}: {exc.msg} (line {exc.lineno})")
    except (ValueError, RecursionError) as exc:
        return Symbols(error=f"could not parse {filename}: {exc}")

    collector = _Collector()
    collector.visit(tree)
    return Symbols(
        bound=frozenset(collector.bound),
        loaded=frozenset(collector.loaded),
        definitions=tuple(_definitions(tree)),
        exports=tuple(_exports(tree)),
        star_import=collector.star_import,
        lines=dict(collector.lines),
    )


def _definitions(tree: ast.Module) -> list[str]:
    """Module-level functions and classes — a module's surface."""
    return [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]


def _exports(tree: ast.Module) -> list[str]:
    """Names listed in ``__all__``: an explicit, checkable API contract."""
    for node in tree.body:
        targets = (
            node.targets if isinstance(node, ast.Assign)
            else [node.target] if isinstance(node, ast.AnnAssign) else []
        )
        if not any(isinstance(t, ast.Name) and t.id == "__all__" for t in targets):
            continue
        value = node.value
        if isinstance(value, (ast.List, ast.Tuple)):
            return [
                item.value for item in value.elts
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            ]
    return []


class _Collector(ast.NodeVisitor):
    """Every binding and every load, anywhere in the module."""

    def __init__(self) -> None:
        self.bound: set[str] = set()
        self.loaded: set[str] = set()
        self.lines: dict[str, int] = {}
        self.star_import = False

    # -- bindings --------------------------------------------------------
    def visit_FunctionDef(self, node) -> None:
        self.bound.add(node.name)
        self._arguments(node.args)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, node) -> None:
        self._arguments(node.args)
        self.generic_visit(node)

    def visit_ClassDef(self, node) -> None:
        self.bound.add(node.name)
        self.generic_visit(node)

    def visit_Import(self, node) -> None:
        for alias in node.names:
            self.bound.add(alias.asname or alias.name.split(".")[0])

    def visit_ImportFrom(self, node) -> None:
        for alias in node.names:
            if alias.name == "*":
                self.star_import = True
                continue
            self.bound.add(alias.asname or alias.name)

    def visit_ExceptHandler(self, node) -> None:
        if node.name:
            self.bound.add(node.name)
        self.generic_visit(node)

    def visit_Global(self, node) -> None:
        self.bound.update(node.names)

    def visit_Nonlocal(self, node) -> None:
        self.bound.update(node.names)

    def visit_MatchAs(self, node) -> None:
        if node.name:
            self.bound.add(node.name)
        self.generic_visit(node)

    def visit_MatchStar(self, node) -> None:
        if node.name:
            self.bound.add(node.name)

    def visit_MatchMapping(self, node) -> None:
        if node.rest:
            self.bound.add(node.rest)
        self.generic_visit(node)

    def visit_Name(self, node) -> None:
        if isinstance(node.ctx, ast.Load):
            self.loaded.add(node.id)
            self.lines.setdefault(node.id, node.lineno)
        else:  # Store and Del both bind or unbind a module-level name
            self.bound.add(node.id)

    def _arguments(self, args: ast.arguments) -> None:
        for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs):
            self.bound.add(arg.arg)
        for optional in (args.vararg, args.kwarg):
            if optional is not None:
                self.bound.add(optional.arg)
