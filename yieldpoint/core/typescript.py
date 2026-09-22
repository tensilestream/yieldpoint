"""Structural measurement of TypeScript and JavaScript.

The review's item #4: *"If it only handles Python, it's a Python tool."* This
is the second language, and the honesty about its depth matters more than the
fact of it.

**What it does.** The same structural measures Python gets — file length,
function length, parameter count, nesting, cyclomatic complexity — and the
swallowed-exception rule, which is the most on-thesis of them.

**What it does not.** Assertion monotonicity, the rule this package is really
about, is still Python-only. A weakened `expect()` is not detected. Anyone
reading `yieldpoint languages` is told so, because a language listed as
supported when only half the rules run is the false-green this whole project
exists to complain about.

**Optional by design.** A real parser is a dependency, and the core does not
take dependencies. Without `tree-sitter` installed, TypeScript files stay
reported as not evaluated — never as clean. Depth is opt-in; silence is not.
"""

from __future__ import annotations

from .metrics import FunctionMetrics, ModuleMetrics

SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")

#: Nodes that hold a callable body worth measuring on its own.
_FUNCTIONS = frozenset({
    "function_declaration", "function_expression", "generator_function_declaration",
    "method_definition", "arrow_function",
})

#: Statements that open a level, as a reader counts them.
#: ``catch_clause`` is deliberately absent: it sits inside ``try_statement``,
#: which has already counted the level. Counting both makes a plain
#: try/catch read as two levels deep, the same way an ``elif`` chain once
#: read as four in the Python measurer.
_NESTING = frozenset({
    "if_statement", "for_statement", "for_in_statement", "while_statement",
    "do_statement", "try_statement", "switch_statement",
})

#: Nodes that add a path through the code.
_BRANCHES = frozenset({
    "if_statement", "for_statement", "for_in_statement", "while_statement",
    "do_statement", "catch_clause", "ternary_expression", "switch_case",
})

#: `&&` and `||` each add a path, the same way a Python ``BoolOp`` does.
_SHORT_CIRCUIT = frozenset({"&&", "||", "??"})

_COMMENTS = frozenset({"comment"})


def available() -> bool:
    """Whether a parser is installed. False means these files stay unevaluated."""
    try:
        import tree_sitter  # noqa: F401
        import tree_sitter_typescript  # noqa: F401
    except ImportError:
        return False
    return True


def _parser(filename: str):
    from tree_sitter import Language, Parser
    import tree_sitter_typescript as grammar

    dialect = (grammar.language_tsx() if filename.endswith(".tsx")
               else grammar.language_typescript())
    return Parser(Language(dialect))


def _name(node) -> str:
    named = node.child_by_field_name("name")
    if named is not None and named.text:
        return named.text.decode("utf-8", "replace")
    return "(anonymous)"


def _parameters(node) -> int:
    params = node.child_by_field_name("parameters")
    if params is None:
        return 1 if node.type == "arrow_function" else 0
    return sum(1 for child in params.named_children if child.type not in _COMMENTS)


def _survey(node, depth: int = 0) -> tuple[int, int, int]:
    """Statements, deepest nesting and branches under one node."""
    statements, deepest, branches = 0, depth, 0
    for child in node.children:
        if child.type.endswith("_statement") or child.type.endswith("_declaration"):
            statements += 1
        if child.type in _BRANCHES:
            branches += 1
        if child.type == "binary_expression":
            operator = child.child_by_field_name("operator")
            if operator is not None and operator.type in _SHORT_CIRCUIT:
                branches += 1
        step = depth + 1 if child.type in _NESTING else depth
        inner_statements, inner_depth, inner_branches = _survey(child, step)
        statements += inner_statements
        branches += inner_branches
        deepest = max(deepest, inner_depth)
    return statements, deepest, branches


def _function(node, prefix: str) -> FunctionMetrics:
    name = _name(node)
    qualname = f"{prefix}{name}"
    statements, nesting, branches = _survey(node)
    return FunctionMetrics(
        name=name, qualname=qualname, line=node.start_point[0] + 1,
        lines=node.end_point[0] - node.start_point[0] + 1,
        parameters=_parameters(node), nesting=nesting, complexity=branches + 1,
        shape="", statements=statements,
    )


def _walk(node, prefix: str, out: list) -> None:
    for child in node.children:
        if child.type in _FUNCTIONS:
            out.append(_function(child, prefix))
            _walk(child, f"{prefix}{_name(child)}.", out)
        elif child.type in ("class_declaration", "class"):
            _walk(child, f"{prefix}{_name(child)}.", out)
        else:
            _walk(child, prefix, out)


def _code_lines(source: str) -> int:
    """Lines that are neither blank nor a comment, matching the Python count."""
    total, block = 0, False
    for raw in source.splitlines():
        line = raw.strip()
        if block:
            block = "*/" not in line
            continue
        if not line or line.startswith("//"):
            continue
        if line.startswith("/*"):
            block = "*/" not in line
            continue
        total += 1
    return total


def measure(source: str, *, filename: str = "<source>") -> ModuleMetrics:
    """Measure one module. Never raises; reports why when it cannot."""
    if not available():
        return ModuleMetrics(error=(
            "TypeScript support needs the `tree-sitter` and "
            "`tree-sitter-typescript` packages; install them or these files "
            "stay unevaluated"))
    try:
        tree = _parser(filename).parse(source.encode("utf-8"))
    except (ValueError, RecursionError, OSError) as exc:
        return ModuleMetrics(error=f"could not parse {filename}: {exc}")

    functions: list[FunctionMetrics] = []
    _walk(tree.root_node, "", functions)
    return ModuleMetrics(
        lines=len(source.splitlines()),
        code_lines=_code_lines(source),
        definitions=sum(1 for c in tree.root_node.children
                        if c.type in _FUNCTIONS or c.type.startswith("class")),
        functions=tuple(functions),
    )


__all__ = ["SUFFIXES", "available", "measure"]
