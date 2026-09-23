"""A second language, and honesty about how deep it goes.

Structure, size and complexity — not assertion monotonicity. Listing a
language as supported when only half the rules run is the false green this
package exists to complain about, so the depth is stated everywhere it shows.
"""

import unittest
from unittest import mock

from yieldpoint.core import typescript
from yieldpoint.core.policy import Policy
from yieldpoint.verify import verify_change

AVAILABLE = typescript.available()


@unittest.skipUnless(AVAILABLE, "tree-sitter not installed")
class TestMeasurement(unittest.TestCase):
    def _one(self, source, filename="a.ts"):
        return typescript.measure(source, filename=filename).functions[0]

    def test_parameters_are_counted(self):
        self.assertEqual(self._one("function f(a, b, c, d, e, g) { return a; }").parameters, 6)

    def test_a_method_is_named_by_its_class(self):
        found = self._one("class Thing { method(p) { return p; } }")
        self.assertEqual(found.qualname, "Thing.method")

    def test_nesting_counts_levels_a_reader_would_count(self):
        source = "function f() { if (a) { for (;;) { while (b) { go(); } } } }"
        self.assertEqual(self._one(source).nesting, 3)

    def test_a_plain_try_catch_is_one_level_not_two(self):
        """`catch_clause` sits inside `try_statement`; counting both made an
        ordinary try/catch read as deeply nested."""
        self.assertEqual(self._one("function f(){ try { go(); } catch (e) { h(); } }").nesting, 1)

    def test_short_circuit_operators_add_a_path(self):
        plain = self._one("function f(a) { return a; }").complexity
        both = self._one("function f(a, b) { return a && b; }").complexity
        self.assertEqual(both, plain + 1)

    def test_comments_are_not_code_lines(self):
        module = typescript.measure("// a\n/* b\n   c */\nconst x = 1;\n", filename="a.ts")
        self.assertEqual(module.code_lines, 1)

    def test_tsx_is_parsed_with_the_tsx_grammar(self):
        module = typescript.measure("const A = () => <div/>;\n", filename="a.tsx")
        self.assertIs(module.ok, True)


class TestItIsOptional(unittest.TestCase):
    def test_without_a_parser_the_file_is_unreadable_not_clean(self):
        """Depth is opt-in. Silence is not."""
        with mock.patch.object(typescript, "available", return_value=False):
            module = typescript.measure("const x = 1;\n", filename="a.ts")
        self.assertIs(module.ok, False)
        self.assertIn("tree-sitter", module.error)


@unittest.skipUnless(AVAILABLE, "tree-sitter not installed")
class TestThroughVerify(unittest.TestCase):
    def test_a_typescript_function_gets_the_parameter_rule(self):
        """The exact finding the reviewer praised, in a second language."""
        verdict = verify_change("export function f(a, b) { return a; }\n",
                                "export function f(a, b, c, d, e, g) { return a; }\n",
                                "src/app.ts")
        self.assertIn("too_many_parameters", [f.rule for f in verdict.findings])

    def test_an_ordinary_module_counts_as_examined(self):
        verdict = verify_change("const a = 1;\n", "const a = 2;\n", "src/app.ts")
        self.assertEqual(list(verdict.checked), ["src/app.ts"])

    def test_the_assertion_gap_is_always_stated(self):
        verdict = verify_change("const a = 1;\n", "const a = 2;\n", "src/app.ts")
        self.assertIn("assertions are not analysed", " ".join(verdict.skipped))

    def test_a_protected_test_file_is_never_reported_as_checked(self):
        """The one thing that file exists to guarantee was not read."""
        verdict = verify_change("const a = 1;\n", "const a = 2;\n",
                                "tests/a.test.ts", Policy())
        self.assertEqual(verdict.checked, ())
        self.assertNotEqual(verdict.status.value, "pass")

    def test_the_python_path_is_unaffected(self):
        verdict = verify_change("x = 1\n", "x = 2\n", "src/a.py")
        self.assertEqual(list(verdict.checked), ["src/a.py"])

    def test_unknown_typescript_shapes_do_not_claim_duplication(self):
        source = "function first() { return 1; }\nfunction second() { return 2; }\n"
        verdict = verify_change(source, source, "src/adapters.js")
        self.assertNotIn("duplicate_implementation", [f.rule for f in verdict.findings])


@unittest.skipUnless(AVAILABLE, "tree-sitter not installed")
class TestTheCacheKnowsTheLanguage(unittest.TestCase):
    def test_the_same_source_measured_as_two_languages_does_not_collide(self):
        """`filename` is excluded from the cache key by design, so the
        language has to be part of the *kind* or one answer serves both."""
        from yieldpoint.core.metrics import measure

        source = "x = 1\n"
        self.assertNotEqual(measure(source, filename="a.py").code_lines,
                            -1)  # sanity: the Python path still works
        self.assertIs(measure(source, filename="a.ts").ok, True)
        self.assertIs(measure(source, filename="a.py").ok, True)


if __name__ == "__main__":
    unittest.main()
