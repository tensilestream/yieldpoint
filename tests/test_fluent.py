"""Assertion style is the project's choice, not this tool's.

A project writing `assert_that(x).is_equal_to(y)` must get the same verdicts as
one writing `assert x == y`. Before this was handled, fluent assertions were
invisible: weakening one passed silently, which is the failure this project
exists to prevent.
"""

import unittest

from aegisflow.core.assertions import extract
from aegisflow.core.policy import Policy
from aegisflow.core.relation import Relation as R
from aegisflow.core.verdict import Status
from aegisflow.verify import verify_change


def only(body: str):
    assertions = extract(f"def test_x():\n    {body}\n").tests[0].assertions
    assert len(assertions) == 1, f"expected 1 assertion, got {len(assertions)}"
    return assertions[0]


class TestFluentChains(unittest.TestCase):
    def test_assertpy(self):
        found = only("assert_that(inv.total).is_equal_to(42)")
        self.assertEqual((found.subject, found.relation), ("inv.total", R.EQ))

    def test_assertj_camel_case(self):
        found = only("assertThat(inv.getTotal()).isEqualTo(42)")
        self.assertIs(found.relation, R.EQ)

    def test_jest_and_chai(self):
        self.assertIs(only('expect(inv.currency).to_equal("USD")').relation, R.EQ)
        self.assertIs(only("expect(x).toBe(3)").relation, R.EQ)
        self.assertIs(only("expect(x).to.equal(3)").relation, R.EQ)

    def test_subject_comes_from_the_chain_root_not_the_terminal(self):
        self.assertEqual(only("assert_that(inv.total).is_equal_to(42)").subject, "inv.total")

    def test_weak_terminals_are_ranked_weak(self):
        self.assertIs(only("assert_that(x).is_not_none()").relation, R.NON_NULL)
        self.assertIs(only("expect(x).toBeDefined()").relation, R.NON_NULL)
        self.assertIs(only("assert_that(x).is_true()").relation, R.TRUTHY)

    def test_membership_and_bounds(self):
        self.assertIs(only('assert_that(items).contains("pen")').relation, R.MEMBERSHIP)
        self.assertIs(only("assert_that(x).is_greater_than(5)").relation, R.COMPARISON)
        self.assertIs(only("assert_that(x).is_instance_of(int)").relation, R.MEMBERSHIP)

    def test_raises(self):
        self.assertIs(only("expect(boom).toThrow(ValueError)").relation, R.RAISES)

    def test_negation_weakens_an_exact_claim(self):
        """`not equal to x` bounds the value; it does not pin it."""
        self.assertIs(only('expect(x).not_.to_be("y")').relation, R.COMPARISON)

    def test_unknown_terminal_is_opaque_not_discarded(self):
        found = only("assert_that(inv.total).is_frobnicated(3)")
        self.assertIs(found.relation, R.OPAQUE)
        self.assertEqual(found.subject, "inv.total")


class TestMatcherStyle(unittest.TestCase):
    def test_hamcrest_equal_to(self):
        found = only("assert_that(inv.tax, equal_to(0))")
        self.assertEqual((found.subject, found.relation), ("inv.tax", R.EQ))

    def test_hamcrest_weak_matcher(self):
        self.assertIs(only("assert_that(x, not_none())").relation, R.NON_NULL)

    def test_hamcrest_membership(self):
        self.assertIs(only("assert_that(items, has_item(3))").relation, R.MEMBERSHIP)


class TestStyleIsNeutral(unittest.TestCase):
    PATH = "tests/test_invoice.py"

    def verdict(self, before, after):
        return verify_change(before, after, self.PATH, Policy())

    PLAIN = "def test_total(inv):\n    assert inv.total == 42\n"
    FLUENT = (
        "from assertpy import assert_that\n\n"
        "def test_total(inv):\n    assert_that(inv.total).is_equal_to(42)\n"
    )
    MATCHER = (
        "from hamcrest import assert_that, equal_to\n\n"
        "def test_total(inv):\n    assert_that(inv.total, equal_to(42))\n"
    )

    def test_migrating_plain_to_fluent_is_not_a_weakening(self):
        self.assertIs(self.verdict(self.PLAIN, self.FLUENT).status, Status.PASS)

    def test_migrating_fluent_to_plain_is_not_a_weakening(self):
        self.assertIs(self.verdict(self.FLUENT, self.PLAIN).status, Status.PASS)

    def test_migrating_to_matcher_style_is_not_a_weakening(self):
        self.assertIs(self.verdict(self.PLAIN, self.MATCHER).status, Status.PASS)

    def test_weakening_a_fluent_assertion_is_caught(self):
        before = self.FLUENT
        after = self.FLUENT.replace("is_equal_to(42)", "is_not_none()")
        verdict = self.verdict(before, after)
        self.assertIs(verdict.status, Status.REPAIR)
        self.assertIn("weakened", verdict.findings[0].detail)

    def test_weakening_across_styles_is_caught(self):
        """Switching style must not be a way to smuggle a downgrade past."""
        after = self.FLUENT.replace("is_equal_to(42)", "is_not_none()")
        self.assertIs(self.verdict(self.PLAIN, after).status, Status.REPAIR)

    def test_deleting_a_fluent_assertion_is_caught(self):
        before = self.FLUENT
        after = "from assertpy import assert_that\n\ndef test_total(inv):\n    pass\n"
        self.assertIsNot(self.verdict(before, after).status, Status.PASS)


class TestUnrecognisedStyle(unittest.TestCase):
    """A style we do not read must degrade, not accuse."""

    def test_unknown_style_is_not_called_an_empty_test(self):
        source = "def test_x(inv):\n    inv.total.should.equal(42)\n"
        verdict = verify_change(None, source, "tests/test_x.py", Policy())
        self.assertIs(verdict.status, Status.PASS)

    def test_unclassified_calls_are_recorded(self):
        case = extract("def test_x():\n    inv.total.should.equal(42)\n").tests[0]
        self.assertTrue(case.unclassified_calls)

    def test_a_genuinely_empty_test_is_still_caught(self):
        source = "def setup_database():\n    pass\n\ndef test_x():\n    setup_database()\n"
        verdict = verify_change(None, source, "tests/test_x.py", Policy())
        self.assertEqual([f.rule for f in verdict.findings], ["empty_test"])

    def test_ordinary_setup_calls_are_not_mistaken_for_assertions(self):
        case = extract("def test_x():\n    setup_database()\n    assert a == 1\n").tests[0]
        self.assertEqual(len(case.assertions), 1)


if __name__ == "__main__":
    unittest.main()
