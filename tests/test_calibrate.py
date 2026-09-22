"""Thresholds measured from a repository rather than asserted at it."""

import json
import tempfile
import unittest
from pathlib import Path

from yieldpoint.calibrate import ENOUGH, Measured, describe, survey
from yieldpoint.core.policy import Policy


def _repo(lengths):
    root = Path(tempfile.mkdtemp())
    for index, lines in enumerate(lengths):
        (root / f"m{index}.py").write_text("\n".join(f"x{i} = 1" for i in range(lines)) + "\n")
    return root


class TestMeasured(unittest.TestCase):
    def test_the_median_is_the_middle(self):
        self.assertEqual(Measured("m", (1, 5, 9)).median, 5)

    def test_the_share_over_a_limit_is_counted(self):
        self.assertEqual(Measured("m", (10, 20, 30, 40)).over(25), 0.5)

    def test_no_limit_means_nothing_is_over_it(self):
        self.assertEqual(Measured("m", (10, 20)).over(0), 0.0)

    def test_a_proposal_leaves_roughly_a_tenth_over(self):
        found = Measured("m", tuple(range(1, 101)))
        self.assertLessEqual(found.over(found.proposal), 0.15)

    def test_a_proposal_is_a_number_a_person_would_have_typed(self):
        self.assertEqual(Measured("m", tuple([120] * 50)).proposal % 50, 0)

    def test_too_few_files_is_not_enough_to_generalise_from(self):
        self.assertIs(Measured("m", (1, 2, 3)).enough, False)
        self.assertIs(Measured("m", tuple(range(ENOUGH))).enough, True)


class TestSurvey(unittest.TestCase):
    def test_it_measures_the_files_it_would_analyse(self):
        found = survey(_repo([10, 20, 30]), Policy())
        self.assertEqual(sorted(found.values), [10, 20, 30])

    def test_an_empty_repository_proposes_nothing(self):
        self.assertIn("No Python files", describe(survey(_repo([]), Policy())))


class TestDescribe(unittest.TestCase):
    def test_it_says_what_the_proposal_would_cost_today(self):
        text = describe(survey(_repo([50] * 20 + [900]), Policy()))
        self.assertIn("median", text)
        self.assertIn("leaves", text)

    def test_it_compares_against_the_number_the_review_complained_about(self):
        """300 appeared in no file the reviewer could open. Now it is priced."""
        self.assertIn("300 would leave", describe(survey(_repo([50] * 20), Policy())))

    def test_too_few_files_declines_to_propose_rather_than_guessing(self):
        text = describe(survey(_repo([10, 20]), Policy()))
        self.assertIn("too few", text)


class TestInitUsesIt(unittest.TestCase):
    def test_a_measured_limit_is_written_into_a_new_policy(self):
        from yieldpoint.policyfile import FILENAME, ensure

        root = _repo([100] * 20 + [800])
        written = ensure(root)
        raw = json.loads((root / FILENAME).read_text())
        self.assertIsNotNone(raw["structure"]["max_file_lines"])
        self.assertIn("median", written.measured)

    def test_a_repository_too_small_to_measure_keeps_the_rule_off(self):
        """An arbitrary number is worse than no number."""
        from yieldpoint.policyfile import FILENAME, ensure

        root = _repo([10, 20])
        ensure(root)
        raw = json.loads((root / FILENAME).read_text())
        self.assertIsNone(raw["structure"]["max_file_lines"])

    def test_an_existing_policy_is_not_recalibrated(self):
        from yieldpoint.policyfile import FILENAME, ensure

        root = _repo([100] * 20)
        (root / FILENAME).write_text('{"structure": {"max_file_lines": 42}}')
        ensure(root)
        raw = json.loads((root / FILENAME).read_text())
        self.assertEqual(raw["structure"]["max_file_lines"], 42)


if __name__ == "__main__":
    unittest.main()
