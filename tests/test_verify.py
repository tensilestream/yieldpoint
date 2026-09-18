"""Stage 3 gate: one call, policy-driven verdict, nothing silently passed."""

import unittest

from aegisflow.core.policy import Policy
from aegisflow.core.verdict import Status
from aegisflow.verify import ASSERTION_MONOTONICITY, verify_change

BEFORE = """
from decimal import Decimal

from app import build


def test_invoice_total():
    inv = build(qty=2, price=21)
    assert inv.total == Decimal("42.00")
    assert inv.currency == "USD"
"""

WEAKENED = """
from decimal import Decimal

from app import build


def test_invoice_total():
    inv = build(qty=2, price=21)
    assert inv.total is not None
    assert inv.currency == "USD"
"""

PATH = "tests/test_invoice.py"


class TestVerdicts(unittest.TestCase):
    def test_weakening_is_reported_with_policy_severity(self):
        verdict = verify_change(BEFORE, WEAKENED, PATH, Policy())
        self.assertIs(verdict.status, Status.REPAIR)
        self.assertEqual(verdict.findings[0].rule, ASSERTION_MONOTONICITY)
        self.assertEqual(verdict.checked, (PATH,))

    def test_unchanged_file_passes(self):
        verdict = verify_change(BEFORE, BEFORE, PATH, Policy())
        self.assertIs(verdict.status, Status.PASS)
        self.assertTrue(verdict)

    def test_severity_comes_from_policy(self):
        policy = Policy.from_dict({"test_contract": {"assertion_monotonicity": "escalate"}})
        self.assertIs(verify_change(BEFORE, WEAKENED, PATH, policy).status, Status.ESCALATE)

    def test_disabled_rule_produces_no_finding(self):
        policy = Policy.from_dict({"test_contract": {"assertion_monotonicity": "off"}})
        self.assertIs(verify_change(BEFORE, WEAKENED, PATH, policy).status, Status.PASS)

    def test_finding_carries_location_and_remedy(self):
        finding = verify_change(BEFORE, WEAKENED, PATH, Policy()).findings[0]
        self.assertEqual(finding.file, PATH)
        self.assertEqual(finding.symbol, "test_invoice_total")
        self.assertIn("inv.total", finding.prescription)
        self.assertIn("Decimal", finding.before)


class TestScope(unittest.TestCase):
    def test_non_test_file_is_not_subject_to_the_test_contract(self):
        verdict = verify_change(BEFORE, WEAKENED, "src/invoice.py", Policy())
        self.assertIs(verdict.status, Status.PASS)
        self.assertEqual(verdict.checked, ("src/invoice.py",))

    def test_protected_patterns_come_from_policy(self):
        policy = Policy.from_dict({"test_contract": {"protected_patterns": ["src/**"]}})
        self.assertFalse(verify_change(BEFORE, WEAKENED, PATH, policy).findings)
        self.assertTrue(verify_change(BEFORE, WEAKENED, "src/a.py", policy).findings)


class TestNothingIsSilentlyPassed(unittest.TestCase):
    """A file that was not analysed must never look like a file that passed."""

    def test_unsupported_language_is_skipped_not_passed(self):
        verdict = verify_change(BEFORE, WEAKENED, "tests/a.test.ts", Policy())
        self.assertEqual(verdict.checked, ())
        self.assertEqual(len(verdict.skipped), 1)
        self.assertIn("no exact analyser", verdict.skipped[0])

    def test_unparseable_after_state_is_skipped(self):
        verdict = verify_change(BEFORE, "def test_x(:", PATH, Policy())
        self.assertEqual(verdict.checked, ())
        self.assertIn("unparseable", verdict.skipped[0])

    def test_unparseable_before_state_is_skipped(self):
        verdict = verify_change("def test_x(:", BEFORE, PATH, Policy())
        self.assertIn("before state unparseable", verdict.skipped[0])


class TestFileLifecycle(unittest.TestCase):
    def test_new_file_has_no_before_state(self):
        verdict = verify_change(None, BEFORE, PATH, Policy())
        self.assertIs(verdict.status, Status.PASS)

    def test_new_file_with_a_tautology_is_reported(self):
        verdict = verify_change(None, "def test_a():\n    assert True\n", PATH, Policy())
        self.assertEqual([f.rule for f in verdict.findings], ["vacuous_assertion"])

    def test_deleting_a_test_file_loses_every_subject(self):
        verdict = verify_change(BEFORE, None, PATH, Policy())
        self.assertEqual(len(verdict.findings), 2)


class TestDeduplication(unittest.TestCase):
    def test_emptied_test_reports_once_not_per_subject(self):
        verdict = verify_change(BEFORE, "def test_invoice_total():\n    pass\n", PATH, Policy())
        self.assertEqual([f.rule for f in verdict.findings], ["empty_test"])


class TestCrossFile(unittest.TestCase):
    def test_subject_covered_elsewhere_is_not_a_loss(self):
        from aegisflow.core.relation import Relation

        after = "def test_invoice_total(inv):\n    assert inv.currency == 'USD'\n"
        verdict = verify_change(
            BEFORE, after, PATH, Policy(), also_covered={"inv.total": Relation.EQ}
        )
        self.assertIs(verdict.status, Status.PASS)


if __name__ == "__main__":
    unittest.main()
