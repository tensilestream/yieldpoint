"""Languages read by shape rather than by parsing.

Two things must hold, and the second matters more than the first.

**It catches real weakening** in the frameworks people use. That is what makes
polyglot support worth having at all.

**It never blocks.** A lexical reading can be wrong in ways a parse cannot, so
every finding here carries ``Confidence.LEXICAL``, and nothing lexical is
permitted to stop work. The timidity is deliberate: a construct it does not
recognise yields nothing, and a file it did not understand is reported as
unverified rather than clean.
"""

from __future__ import annotations

import unittest

from yieldpoint.core.lexical import extract, reads
from yieldpoint.core.verdict import Confidence, Status
from yieldpoint.verify import verify_change

POLICY = {"test_contract": {"protected_patterns": [
    "**/*.test.ts", "**/*.test.js", "**/*.spec.ts",
    "**/*Test.java", "**/*Test.kt", "**/*_test.go",
    # Added as each language was: a pattern missing here reads as the rule
    # failing, when in fact the file was never protected.
    "**/*_test.rs", "**/*Test.cs", "**/*_test.rb", "**/*Test.php",
    "**/*Tests.swift", "**/*_test.exs",
]}}

JEST = 'it("totals", () => {\n  expect(invoice.total).toBe(42);\n});\n'
JEST_WEAK = 'it("totals", () => {\n  expect(invoice.total).toBeDefined();\n});\n'

JUNIT = ("class InvoiceTest {\n  @Test\n  public void totals() {\n"
         "    assertEquals(42, invoice.getTotal());\n  }\n}\n")
JUNIT_WEAK = ("class InvoiceTest {\n  @Test\n  public void totals() {\n"
              "    assertNotNull(invoice.getTotal());\n  }\n}\n")

GO = ("func TestTotal(t *testing.T) {\n"
      "    assert.Equal(t, 42, invoice.Total);\n}\n")
GO_WEAK = ("func TestTotal(t *testing.T) {\n"
           "    assert.NotNil(t, invoice.Total);\n}\n")

CHAI = ('it("totals", function () {\n  expect(invoice.total).to.equal(42);\n});\n')
CHAI_WEAK = ('it("totals", function () {\n  expect(invoice.total).to.exist;\n});\n')

KOTLIN = "fun `totals correctly`() {\n    assertThat(invoice.total).isEqualTo(42)\n}\n"
KOTLIN_WEAK = "fun `totals correctly`() {\n    assertThat(invoice.total).isNotNull()\n}\n"


class TestItReadsTheFrameworks(unittest.TestCase):
    FRAMEWORKS = {
        "jest": (JEST, "invoice.total", "eq"),
        "junit": (JUNIT, "invoice.getTotal()", "eq"),
        "testify": (GO, "invoice.Total", "eq"),
        "chai": (CHAI, "invoice.total", "eq"),
        "kotest": (KOTLIN, "invoice.total", "eq"),
    }

    def test_each_yields_the_subject_and_relation(self):
        for name, (source, subject, relation) in self.FRAMEWORKS.items():
            with self.subTest(name):
                tests, recognised = extract(source)
                self.assertTrue(recognised, f"{name} was not recognised")
                found = {(a.subject, a.relation.value)
                         for t in tests for a in t.assertions}
                self.assertIn((subject, relation), found)


class TestItCatchesWeakening(unittest.TestCase):
    CASES = {
        "typescript": ("src/invoice.test.ts", JEST, JEST_WEAK),
        "java": ("src/InvoiceTest.java", JUNIT, JUNIT_WEAK),
        "go": ("src/invoice_test.go", GO, GO_WEAK),
        "chai": ("src/invoice.test.js", CHAI, CHAI_WEAK),
        "kotlin": ("src/InvoiceTest.kt", KOTLIN, KOTLIN_WEAK),
    }

    def test_a_downgrade_is_reported(self):
        for name, (path, before, after) in self.CASES.items():
            with self.subTest(name):
                verdict = verify_change(before, after, path, POLICY)
                rules = {f.rule for f in verdict.findings}
                self.assertIn("assertion_monotonicity", rules, f"{name} missed it")

    def test_an_unchanged_file_is_clean(self):
        for name, (path, before, _after) in self.CASES.items():
            with self.subTest(name):
                self.assertEqual(
                    verify_change(before, before, path, POLICY).findings, ()
                )


class TestItNeverBlocks(unittest.TestCase):
    """The guarantee that makes a lexical reading safe to ship."""

    def test_every_lexical_finding_says_it_is_lexical(self):
        verdict = verify_change(JEST, JEST_WEAK, "src/a.test.ts", POLICY)
        self.assertTrue(verdict.findings)
        for finding in verdict.findings:
            self.assertIs(finding.confidence, Confidence.LEXICAL)
            self.assertFalse(finding.confidence.may_block)

    def test_configuring_block_degrades_rather_than_raises(self):
        strict = {"test_contract": {
            **POLICY["test_contract"], "assertion_monotonicity": "block",
        }}
        verdict = verify_change(JEST, JEST_WEAK, "src/a.test.ts", strict)
        self.assertTrue(verdict.findings)
        for finding in verdict.findings:
            self.assertIsNot(finding.status, Status.BLOCK)

    def test_python_is_still_exact_and_may_block(self):
        before = "def test_x():\n    assert total == 42\n"
        after = "def test_x():\n    assert total\n"
        verdict = verify_change(before, after, "tests/test_x.py",
                                {"test_contract": {
                                    "protected_patterns": ["**/test_*.py"]}})
        self.assertIs(verdict.findings[0].confidence, Confidence.EXACT)


class TestNativeGoTests(unittest.TestCase):
    """Go's standard library has no assertion API.

    The idiom is a guard that fails the test, so the assertion is the negation
    of the guard. Missing it means missing most Go tests ever written, since
    many projects deliberately avoid a testify dependency.
    """

    def _read(self, body: str):
        tests, understood = extract(
            f"func TestTotal(t *testing.T) {{\n{body}\n}}\n",
            filename="x_test.go")
        return [(a.subject, a.relation.value) for t in tests for a in t.assertions]

    def test_an_inequality_guard_asserts_equality(self):
        self.assertEqual(
            self._read('\tif got != want {\n\t\tt.Errorf("got %v", got)\n\t}'),
            [("got", "eq")])

    def test_a_negation_guard_asserts_truthiness(self):
        self.assertEqual(
            self._read('\tif !ok {\n\t\tt.Error("not ok")\n\t}'),
            [("ok", "truthy")])

    def test_an_ordering_guard_asserts_a_comparison(self):
        self.assertEqual(
            self._read('\tif n < 3 {\n\t\tt.Fatalf("too few: %d", n)\n\t}'),
            [("n", "comparison")])

    def test_every_failing_call_counts(self):
        for call in ("t.Fatal", "t.Fatalf", "t.Error", "t.Errorf"):
            with self.subTest(call=call):
                self.assertEqual(
                    self._read(f'\tif got != want {{\n\t\t{call}("x")\n\t}}'),
                    [("got", "eq")])

    def test_an_error_check_is_plumbing_not_verification(self):
        """`if err != nil` is in nearly every Go test. Reading it as an
        assertion would bury the real ones in noise."""
        self.assertEqual(
            self._read('\tif err != nil {\n\t\tt.Fatal(err)\n\t}'), [])

    def test_a_guard_with_no_failing_call_is_not_an_assertion(self):
        self.assertEqual(
            self._read('\tif got != want {\n\t\tlog.Print("x")\n\t}'), [])


class TestGoWeakeningIsCaught(unittest.TestCase):
    STRONG = ("func TestTotal(t *testing.T) {\n"
              '\tif total != 42 {\n\t\tt.Fatal("bad")\n\t}\n}\n')
    WEAK = ("func TestTotal(t *testing.T) {\n"
            '\tif !total {\n\t\tt.Fatal("bad")\n\t}\n}\n')

    def _verify(self, before: str, after: str):
        return verify_change(before, after, "pkg/total_test.go", POLICY)

    def test_downgrading_the_guard_is_reported(self):
        verdict = self._verify(self.STRONG, self.WEAK)
        self.assertIn("assertion_monotonicity",
                      {f.rule for f in verdict.findings})

    def test_strengthening_the_guard_is_silent(self):
        self.assertFalse(self._verify(self.WEAK, self.STRONG).findings)

    def test_adding_error_plumbing_is_silent(self):
        after = ("func TestTotal(t *testing.T) {\n"
                 "\tv, err := run()\n\tif err != nil {\n\t\tt.Fatal(err)\n\t}\n"
                 '\t_ = v\n\tif total != 42 {\n\t\tt.Fatal("bad")\n\t}\n}\n')
        self.assertFalse(self._verify(self.STRONG, after).findings)

    def test_it_still_cannot_block(self):
        """Lexical analysis advises; it never stops a build."""
        verdict = self._verify(self.STRONG, self.WEAK)
        self.assertTrue(all(f.confidence is Confidence.LEXICAL
                            for f in verdict.findings))


class TestItIsTimid(unittest.TestCase):
    def test_an_unrecognised_file_is_unverified_not_clean(self):
        source = "// nothing here resembles a test\nconst x = 1;\n"
        verdict = verify_change(source, source + "\n", "src/a.test.ts", POLICY)
        self.assertIs(verdict.status, Status.UNVERIFIED)
        self.assertEqual(verdict.checked, ())

    def test_a_string_literal_is_never_a_subject(self):
        tests, _ = extract('it("a", () => { expect("literal").toBe("x"); });')
        self.assertEqual([a.subject for t in tests for a in t.assertions], [])

    def test_an_unclosed_block_yields_nothing_rather_than_guessing(self):
        tests, recognised = extract('it("a", () => { expect(x).toBe(1);')
        self.assertFalse(recognised)
        self.assertEqual(tests, ())

    def test_it_only_claims_the_languages_it_reads(self):
        for supported in ("a.test.ts", "Foo_test.go", "a_test.rs", "ATest.cs",
                          "a_test.rb", "ATest.php", "ATests.swift",
                          "total_test.exs", "total_test.ex"):
            self.assertTrue(reads(supported), supported)
        self.assertFalse(reads("a.py"), "Python has an exact path")
        self.assertFalse(reads("a.txt"))
        self.assertFalse(reads("a.hs"), "Haskell is not read yet")


if __name__ == "__main__":
    unittest.main()


class TestContractRulesReachEveryLanguage(unittest.TestCase):
    """Three of the four integrity rules need no control flow.

    Restricting them to Python meant they reached one language of twelve for a
    reason that only ever applied to the fourth. `disabled_assertion` still
    does, because it asks whether a failure can propagate.
    """

    def _rules(self, path: str, before: str, after: str):
        verdict = verify_change(before, after, path, POLICY)
        return sorted({f.rule for f in verdict.findings})

    def test_an_emptied_test_is_reported_in_every_language(self):
        for path, before, after in (
            ("a.test.js", "test('t', () => {\n  expect(x).toBe(1);\n});\n",
             "test('t', () => {\n});\n"),
            ("ATest.java", "class A {\n  @Test void t() {\n    assertEquals(1, x);\n  }\n}\n",
             "class A {\n  @Test void t() {\n  }\n}\n"),
            ("a_test.go", 'func TestT(t *testing.T) {\n\tif x != 1 {\n\t\tt.Fatal("b")\n\t}\n}\n',
             "func TestT(t *testing.T) {\n}\n"),
            ("a_test.rs", "#[test]\nfn t() {\n    assert_eq!(x, 1);\n}\n",
             "#[test]\nfn t() {\n}\n"),
        ):
            with self.subTest(path=path):
                self.assertIn("empty_test", self._rules(path, before, after))

    def test_a_newly_skipped_test_is_reported_in_every_language(self):
        for path, before, after in (
            ("a.test.js", "test('t', () => {\n  expect(x).toBe(1);\n});\n",
             "test.skip('t', () => {\n  expect(x).toBe(1);\n});\n"),
            ("ATest.java", "class A {\n  @Test void t() {\n    assertEquals(1, x);\n  }\n}\n",
             "class A {\n  @Disabled\n  @Test void t() {\n    assertEquals(1, x);\n  }\n}\n"),
            ("a_test.go", 'func TestT(t *testing.T) {\n\tif x != 1 {\n\t\tt.Fatal("b")\n\t}\n}\n',
             'func TestT(t *testing.T) {\n\tt.Skip("flaky")\n\tif x != 1 {\n\t\tt.Fatal("b")\n\t}\n}\n'),
        ):
            with self.subTest(path=path):
                self.assertIn("skip_marker", self._rules(path, before, after))

    def test_a_tautology_is_reported_in_every_language(self):
        for path, before, after in (
            ("a.test.js", "test('t', () => {\n  expect(x).toBe(1);\n});\n",
             "test('t', () => {\n  expect(true).toBe(true);\n});\n"),
            ("ATest.java", "class A {\n  @Test void t() {\n    assertEquals(1, x);\n  }\n}\n",
             "class A {\n  @Test void t() {\n    assertTrue(true);\n  }\n}\n"),
        ):
            with self.subTest(path=path):
                self.assertIn("vacuous_assertion", self._rules(path, before, after))

    def test_a_literal_expectation_is_not_a_tautology(self):
        """`expect(ok).toBe(true)` pins ok. Only a literal *subject* is vacuous."""
        same = "test('t', () => {\n  expect(ok).toBe(true);\n});\n"
        self.assertEqual(self._rules("a.test.js", same, same), [])

    def test_an_expression_subject_is_not_a_constant(self):
        same = "test('t', () => {\n  expect(items.length > 0).toBe(true);\n});\n"
        self.assertEqual(self._rules("a.test.js", same, same), [])

    def test_a_pre_existing_offence_is_not_blamed_on_this_change(self):
        before = "test.skip('t', () => {\n  expect(x).toBe(1);\n});\n"
        self.assertEqual(self._rules("a.test.js", before, before + "// note\n"), [])

    def test_none_of_these_may_block_a_build(self):
        """Lexical analysis advises. A regex must not stop someone's build."""
        verdict = verify_change("test('t', () => {\n  expect(x).toBe(1);\n});\n",
                                "test('t', () => {\n});\n", "a.test.js", POLICY)
        # `empty_test` is the specific finding here; monotonicity defers to it
        # rather than also reporting the assertion that went with the body.
        self.assertEqual(sorted({f.rule for f in verdict.findings}), ["empty_test"])
        self.assertEqual({f.confidence for f in verdict.findings},
                         {Confidence.LEXICAL})
        self.assertNotIn(Status.BLOCK, {f.status for f in verdict.findings})
