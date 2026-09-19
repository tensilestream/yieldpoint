"""The lattice is a partial order; incomparability must never become a finding."""

import unittest

from yieldpoint.core.relation import Relation as R


class TestOrdering(unittest.TestCase):
    def test_equality_dominates_everything_weaker(self):
        for weaker in (R.COMPARISON, R.MEMBERSHIP, R.TRUTHY, R.NON_NULL, R.VACUOUS, R.NONE):
            self.assertTrue(R.EQ.dominates(weaker), weaker)

    def test_the_canonical_weakening_is_a_descent(self):
        # assert x == 3  ->  assert x is not None
        self.assertTrue(R.NON_NULL.descends_from(R.EQ))

    def test_strengthening_is_not_a_descent(self):
        self.assertFalse(R.EQ.descends_from(R.NON_NULL))

    def test_identical_relations_do_not_descend(self):
        for relation in R:
            self.assertFalse(relation.descends_from(relation), relation)


class TestIncomparability(unittest.TestCase):
    def test_siblings_are_incomparable(self):
        self.assertIsNone(R.COMPARISON.dominates(R.MEMBERSHIP))
        self.assertIsNone(R.MEMBERSHIP.dominates(R.RAISES))

    def test_incomparable_pairs_never_produce_a_descent(self):
        self.assertFalse(R.COMPARISON.descends_from(R.MEMBERSHIP))
        self.assertFalse(R.MEMBERSHIP.descends_from(R.COMPARISON))

    def test_opaque_is_comparable_with_nothing(self):
        for other in (R.EQ, R.TRUTHY, R.NONE, R.NON_NULL):
            self.assertIsNone(R.OPAQUE.dominates(other), other)
            self.assertIsNone(other.dominates(R.OPAQUE), other)

    def test_opaque_never_produces_a_descent(self):
        # A helper call hides its assertions; guessing would be a false positive.
        self.assertFalse(R.OPAQUE.descends_from(R.EQ))
        self.assertFalse(R.EQ.descends_from(R.OPAQUE))

    def test_opaque_dominates_itself(self):
        self.assertTrue(R.OPAQUE.dominates(R.OPAQUE))


class TestVerification(unittest.TestCase):
    def test_vacuous_and_none_verify_nothing(self):
        self.assertFalse(R.VACUOUS.verifies_anything)
        self.assertFalse(R.NONE.verifies_anything)

    def test_non_null_still_verifies_something(self):
        self.assertTrue(R.NON_NULL.verifies_anything)

    def test_vacuous_and_none_are_equal_strength(self):
        self.assertTrue(R.NONE.dominates(R.VACUOUS))
        self.assertTrue(R.VACUOUS.dominates(R.NONE))


if __name__ == "__main__":
    unittest.main()
