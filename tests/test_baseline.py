"""Attributing a violation to whoever earned it.

The review that prompted this module reported being blocked on a 1,385-line
file by a change that added one line, with a message that named only 1,386.
These tests pin the distinction the message was missing.
"""

import unittest

from yieldpoint.core.baseline import (
    CARRIED,
    CLEAR,
    IMPROVING,
    INTRODUCED,
    UNCLASSIFIED,
    WORSENED,
    Baseline,
)


class TestClassification(unittest.TestCase):
    def test_within_the_limit_is_not_a_finding(self):
        self.assertEqual(Baseline(200, 300, 100).classification, CLEAR)
        self.assertFalse(Baseline(200, 300, 100).over)

    def test_no_limit_means_the_rule_is_off(self):
        self.assertEqual(Baseline(9_000, 0, 0).classification, CLEAR)

    def test_crossing_the_limit_is_introduced(self):
        self.assertEqual(Baseline(301, 300, 299).classification, INTRODUCED)

    def test_a_file_written_by_this_change_is_introduced(self):
        """No prior measurement of zero is the same as not existing before."""
        self.assertEqual(Baseline(400, 300, 0).classification, INTRODUCED)

    def test_growing_while_already_over_is_worsened(self):
        self.assertEqual(Baseline(1386, 300, 1385).classification, WORSENED)

    def test_unchanged_and_over_is_carried(self):
        self.assertEqual(Baseline(1385, 300, 1385).classification, CARRIED)

    def test_shrinking_while_still_over_is_improving(self):
        self.assertEqual(Baseline(1300, 300, 1385).classification, IMPROVING)

    def test_no_baseline_is_not_silently_treated_as_zero(self):
        """RULES.md section 5: a comparison that could not be made has no result.

        Reporting it as ``introduced`` would blame the change for a file it may
        not have written; reporting it as ``carried`` would excuse one it did.
        """
        self.assertEqual(Baseline(400, 300, None).classification, UNCLASSIFIED)


class TestAttribution(unittest.TestCase):
    def test_worsened_names_both_numbers_and_the_delta(self):
        detail = Baseline(1386, 300, 1385).describe("wb.py", "lines of code")
        self.assertIn("1,385", detail)
        self.assertIn("1,386", detail)
        self.assertIn("+1", detail)
        self.assertIn("already over", detail)

    def test_introduced_does_not_claim_a_baseline_it_did_not_use(self):
        detail = Baseline(301, 300, 299).describe("wb.py", "lines of code")
        self.assertNotIn("already over", detail)
        self.assertNotIn("grew from", detail)

    def test_unclassified_says_so_rather_than_guessing(self):
        detail = Baseline(400, 300, None).describe("wb.py", "lines of code")
        self.assertIn("not known", detail)

    def test_the_delta_is_what_this_change_contributed(self):
        self.assertEqual(Baseline(1386, 300, 1385).added, 1)

    def test_an_unknown_baseline_yields_no_delta_rather_than_a_wrong_one(self):
        self.assertEqual(Baseline(1386, 300, None).added, 0)


if __name__ == "__main__":
    unittest.main()
