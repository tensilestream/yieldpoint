"""Accessor normalisation.

A property and its accessor name the same thing:

    invoice.total          invoice.getTotal()      invoice.get_total()
    order.active           order.isActive()        order.is_active()

Refactoring between them — which Lombok, C# properties, Python ``@property`` and
Ruby ``attr_accessor`` all encourage — changes the subject *expression* without
changing what is verified. Compared literally, one subject disappears and another
appears, and a perfectly good refactor is reported as two weakenings.

Normalisation is applied only as a fallback, after exact matching has failed, so
it can **suppress** a false finding but never invent one. Only zero-argument
calls are treated as accessors: ``inv.get(key)`` takes an argument and is a
lookup, not a property.
"""

from __future__ import annotations

import ast

#: Accessor prefixes shared by the JVM, .NET, Python and Ruby conventions.
_PREFIXES = ("get", "is", "has")


def normalize(expression: str) -> str:
    """Rewrite accessor calls in ``expression`` to the property they expose.

    Falls back to the original text when it cannot be parsed, so a failure
    degrades to exact matching rather than to an error.
    """
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, ValueError, RecursionError):
        return expression
    try:
        return ast.unparse(ast.fix_missing_locations(_Accessors().visit(tree)))
    except (ValueError, RecursionError):
        return expression


def property_name(attribute: str) -> str | None:
    """``getTotal`` -> ``total``, ``is_active`` -> ``active``. ``None`` if not an accessor."""
    for prefix in _PREFIXES:
        snake = f"{prefix}_"
        if attribute.startswith(snake) and len(attribute) > len(snake):
            return attribute[len(snake):]
        if (
            attribute.startswith(prefix)
            and len(attribute) > len(prefix)
            and attribute[len(prefix)].isupper()
        ):
            rest = attribute[len(prefix):]
            return rest[0].lower() + rest[1:]
    return None


class _Accessors(ast.NodeTransformer):
    def visit_Call(self, node: ast.Call) -> ast.AST:
        self.generic_visit(node)
        if node.args or node.keywords:
            return node  # arguments mean a lookup or a computation, not a property
        if not isinstance(node.func, ast.Attribute):
            return node

        name = property_name(node.func.attr) or node.func.attr
        return ast.Attribute(value=node.func.value, attr=name, ctx=ast.Load())
