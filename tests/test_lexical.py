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
        self.assertTrue(reads("a.test.ts"))
        self.assertTrue(reads("Foo_test.go"))
        self.assertFalse(reads("a.py"), "Python has an exact path")
        self.assertFalse(reads("a.rb"))
        self.assertFalse(reads("a.txt"))


if __name__ == "__main__":
    unittest.main()
