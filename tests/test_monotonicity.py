"""Stage 2 gate.

Two corpora, and the second one matters more. Any checker can flag a deleted
assertion; one that stays silent through ordinary refactoring is the product.
A false positive here costs trust, and a tool people mute verifies nothing.
"""

import unittest

from aegisflow.core.assertions import extract
from aegisflow.core.monotonicity import DISABLED, DOWNGRADED, REMOVED, compare, pair_tests
from aegisflow.core.relation import Relation


def weakenings(before: str, after: str, **kwargs):
    return compare(extract(before), extract(after), **kwargs)


BASELINE = """
def test_invoice_total():
    inv = build(qty=2, price=21)
    assert inv.total == Decimal("42.00")
    assert inv.currency == "USD"
"""


class TestTamperingIsCaught(unittest.TestCase):
    def test_assertion_deleted(self):
        after = """
def test_invoice_total():
    inv = build(qty=2, price=21)
    assert inv.currency == "USD"
"""
        found = weakenings(BASELINE, after)
        self.assertEqual([w.subject for w in found], ["inv.total"])
        self.assertEqual(found[0].kind, REMOVED)

    def test_assertion_downgraded_while_count_is_unchanged(self):
        """The case coverage cannot see: two assertions before, two after."""
        after = """
def test_invoice_total():
    inv = build(qty=2, price=21)
    assert inv.total is not None
    assert inv.currency == "USD"
"""
        found = weakenings(BASELINE, after)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].kind, DOWNGRADED)
        self.assertIs(found[0].before, Relation.EQ)
        self.assertIs(found[0].after, Relation.NON_NULL)

    def test_replaced_with_a_tautology(self):
        after = """
def test_invoice_total():
    assert True
    assert inv.currency == "USD"
"""
        self.assertIn("inv.total", [w.subject for w in weakenings(BASELINE, after)])

    def test_failure_swallowed_by_bare_except(self):
        after = """
def test_invoice_total():
    inv = build(qty=2, price=21)
    try:
        assert inv.total == Decimal("42.00")
    except Exception:
        pass
    assert inv.currency == "USD"
"""
        found = weakenings(BASELINE, after)
        self.assertEqual([w.kind for w in found], [DISABLED])

    def test_guarded_by_a_false_condition(self):
        after = """
def test_invoice_total():
    inv = build(qty=2, price=21)
    if False:
        assert inv.total == Decimal("42.00")
    assert inv.currency == "USD"
"""
        self.assertEqual([w.kind for w in weakenings(BASELINE, after)], [DISABLED])

    def test_body_emptied(self):
        after = "def test_invoice_total():\n    pass\n"
        self.assertEqual({w.kind for w in weakenings(BASELINE, after)}, {REMOVED})

    def test_whole_test_deleted(self):
        self.assertEqual(len(weakenings(BASELINE, "")), 2)


class TestLegitimateRefactorsAreSilent(unittest.TestCase):
    """Every case here must produce exactly zero findings."""

    def assertClean(self, before: str, after: str):
        found = weakenings(before, after)
        self.assertEqual(found, (), f"false positives: {[w.detail for w in found]}")

    def test_parametrising_several_tests_into_one(self):
        before = """
def test_calc_one():
    assert calc(1) == 2

def test_calc_two():
    assert calc(2) == 4
"""
        after = """
@pytest.mark.parametrize("n,expected", [(1, 2), (2, 4)])
def test_calc(n, expected):
    assert calc(n) == expected
"""
        self.assertClean(before, after)

    def test_renaming_a_test(self):
        self.assertClean(BASELINE, BASELINE.replace("test_invoice_total", "test_total_is_correct"))

    def test_splitting_one_test_into_two(self):
        after = """
def test_total():
    inv = build(qty=2, price=21)
    assert inv.total == Decimal("42.00")

def test_currency():
    inv = build(qty=2, price=21)
    assert inv.currency == "USD"
"""
        self.assertClean(BASELINE, after)

    def test_merging_two_tests_into_one(self):
        before = """
def test_total():
    assert inv.total == Decimal("42.00")

def test_currency():
    assert inv.currency == "USD"
"""
        self.assertClean(before, BASELINE)

    def test_reordering_assertions(self):
        after = """
def test_invoice_total():
    inv = build(qty=2, price=21)
    assert inv.currency == "USD"
    assert inv.total == Decimal("42.00")
"""
        self.assertClean(BASELINE, after)

    def test_extracting_setup_into_a_fixture(self):
        after = """
def test_invoice_total(inv):
    assert inv.total == Decimal("42.00")
    assert inv.currency == "USD"
"""
        self.assertClean(BASELINE, after)

    def test_strengthening_an_assertion(self):
        before = "def test_x():\n    assert total is not None\n"
        after = "def test_x():\n    assert total == 42\n"
        self.assertClean(before, after)

    def test_adding_assertions(self):
        after = BASELINE + "    assert inv.tax == Decimal('0.00')\n"
        self.assertClean(BASELINE, after)

    def test_converting_bare_assert_to_unittest_method(self):
        before = "def test_x():\n    assert a.b == 3\n"
        after = "class TestX:\n    def test_x(self):\n        self.assertEqual(a.b, 3)\n"
        self.assertClean(before, after)

    def test_incomparable_change_is_not_a_descent(self):
        """`x > 5` to `x in xs` constrains a different dimension, not a weaker one."""
        before = "def test_x():\n    assert score > 5\n"
        after = "def test_x():\n    assert score in valid_scores\n"
        self.assertClean(before, after)

    def test_helper_assertion_is_not_compared(self):
        before = "def test_x():\n    assert_valid_invoice(inv)\n"
        after = "def test_x():\n    assert_invoice_is_valid(inv)\n"
        found = weakenings(before, after)
        self.assertEqual([w.kind for w in found], [REMOVED])


class TestCrossFileMoves(unittest.TestCase):
    def test_subject_verified_elsewhere_is_not_a_loss(self):
        after = """
def test_invoice_total():
    inv = build(qty=2, price=21)
    assert inv.currency == "USD"
"""
        elsewhere = {"inv.total": Relation.EQ}
        self.assertEqual(weakenings(BASELINE, after, also_covered=elsewhere), ())

    def test_weaker_coverage_elsewhere_is_still_a_loss(self):
        after = "def test_invoice_total():\n    assert inv.currency == 'USD'\n"
        found = weakenings(BASELINE, after, also_covered={"inv.total": Relation.TRUTHY})
        self.assertEqual([w.kind for w in found], [DOWNGRADED])


class TestPairing(unittest.TestCase):
    def test_identical_names_pair(self):
        pairs = pair_tests(extract(BASELINE), extract(BASELINE))
        self.assertEqual(pairs["test_invoice_total"], "test_invoice_total")

    def test_renamed_test_pairs_by_structure(self):
        renamed = BASELINE.replace("test_invoice_total", "test_renamed")
        pairs = pair_tests(extract(BASELINE), extract(renamed))
        self.assertEqual(pairs.get("test_invoice_total"), "test_renamed")

    def test_unrelated_tests_do_not_pair(self):
        other = "def test_completely_different():\n    assert zzz.qqq in aaa\n"
        self.assertEqual(pair_tests(extract(BASELINE), extract(other)), {})


class TestUnparseableInput(unittest.TestCase):
    def test_broken_after_state_reports_nothing(self):
        """An unparseable side cannot be compared; the caller records it as skipped."""
        self.assertEqual(compare(extract(BASELINE), extract("def test_x(:")), ())

    def test_broken_before_state_reports_nothing(self):
        self.assertEqual(compare(extract("def test_x(:"), extract(BASELINE)), ())


class TestSubjectAliasing(unittest.TestCase):
    """Renaming the local that holds the subject is not a weakening.

    This was a documented false positive until single-assignment locals were
    resolved to the expression they were assigned (subject.py).
    """

    def test_renaming_the_subject_variable_is_not_a_weakening(self):
        before = "def test_x():\n    inv = build()\n    assert inv.total == 42\n"
        after = "def test_x():\n    invoice = build()\n    assert invoice.total == 42\n"
        self.assertEqual(weakenings(before, after), ())

    def test_a_reassigned_name_is_not_resolved(self):
        """``inv`` names two different objects here, so neither may stand for it."""
        before = "def test_x():\n    inv = build()\n    assert inv.total == 42\n"
        after = (
            "def test_x():\n    inv = build()\n    inv = other()\n"
            "    assert inv.total is not None\n"
        )
        self.assertTrue(weakenings(before, after))

    def test_renaming_still_catches_a_real_downgrade(self):
        before = "def test_x():\n    inv = build()\n    assert inv.total == 42\n"
        after = "def test_x():\n    invoice = build()\n    assert invoice.total\n"
        self.assertTrue(weakenings(before, after))


if __name__ == "__main__":
    unittest.main()
