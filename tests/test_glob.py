"""Glob matching must mean the same thing on every host."""

import unittest

from aegisflow.core import glob


class TestNormalize(unittest.TestCase):
    def test_windows_separators_compare_equal_to_posix(self):
        self.assertEqual(glob.normalize(r"src\db\x.py"), "src/db/x.py")

    def test_collapses_duplicate_separators_and_leading_dot(self):
        self.assertEqual(glob.normalize("./src//a.py"), "src/a.py")


class TestMatching(unittest.TestCase):
    def test_double_star_crosses_separators(self):
        self.assertTrue(glob.matches("src/**", "src/a/b/c.py"))
        self.assertFalse(glob.matches("src/**", "lib/a.py"))

    def test_double_star_matches_zero_segments(self):
        self.assertTrue(glob.matches("src/**/a.py", "src/a.py"))
        self.assertTrue(glob.matches("src/**/a.py", "src/deep/nested/a.py"))

    def test_single_star_stays_within_a_segment(self):
        self.assertTrue(glob.matches("*.md", "README.md"))
        self.assertFalse(glob.matches("*.md", "docs/README.md"))

    def test_question_mark_is_exactly_one_character(self):
        self.assertTrue(glob.matches("a?.py", "ab.py"))
        self.assertFalse(glob.matches("a?.py", "abc.py"))

    def test_pattern_is_anchored_at_both_ends(self):
        # A substring match would wrongly flag this; the pattern must anchor.
        self.assertFalse(glob.matches("**/test/**", "src/latest/thing.py"))
        self.assertTrue(glob.matches("**/test/**", "src/test/thing.py"))

    def test_dots_are_literal_not_wildcards(self):
        self.assertFalse(glob.matches("*.test.py", "axtestxpy"))

    def test_windows_path_matches_posix_pattern(self):
        self.assertTrue(glob.matches("src/db/**", r"src\db\x.py"))


class TestHelpers(unittest.TestCase):
    def test_matches_any(self):
        patterns = ["**/tests/**", "**/*_test.py"]
        self.assertTrue(glob.matches_any(patterns, "a/b/calc_test.py"))
        self.assertFalse(glob.matches_any(patterns, "a/b/calc.py"))

    def test_first_match_reports_which_rule_fired(self):
        self.assertEqual(
            glob.first_match(["**/*.spec.js", "**/*_test.py"], "a/b_test.py"),
            "**/*_test.py",
        )
        self.assertIsNone(glob.first_match(["**/*.spec.js"], "a/b.py"))


if __name__ == "__main__":
    unittest.main()
