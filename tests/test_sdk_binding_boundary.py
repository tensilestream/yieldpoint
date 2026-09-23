"""Keep Node and Java as CLI bindings, never shadow rule engines."""

from __future__ import annotations

import unittest
from pathlib import Path

from scripts.rules_reference import RULES


ROOT = Path(__file__).resolve().parents[1]
SDK_SOURCES = (
    ROOT / "sdk" / "node" / "src",
    ROOT / "sdk" / "java" / "src" / "main",
)


class TestSdkBindingBoundary(unittest.TestCase):
    def test_bindings_do_not_copy_python_rule_identifiers(self) -> None:
        sources = {
            path.relative_to(ROOT): path.read_text(encoding="utf-8")
            for directory in SDK_SOURCES for path in directory.rglob("*")
            if path.suffix in {".js", ".java"}
        }
        copied = {
            str(path): rule for path, source in sources.items() for rule in RULES
            if rule in source
        }
        self.assertEqual({}, copied)

    def test_bindings_do_not_import_or_parse_python_rule_implementation(self) -> None:
        forbidden = ("yieldpoint.core", "ast.parse", "tree-sitter", "typescript-eslint")
        sources = "\n".join(
            path.read_text(encoding="utf-8") for directory in SDK_SOURCES
            for path in directory.rglob("*") if path.suffix in {".js", ".java"}
        ).lower()
        self.assertEqual([], [token for token in forbidden if token in sources])
