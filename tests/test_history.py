"""What the ledger already knows about a path, folded for the pre-edit brief.

A rule that fired here before is the cheapest prediction available. These
tests are mostly about the two states that read alike and are not alike:
a path that was analysed and found clean, and a path nothing ever looked at.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from yieldpoint.brief import brief
from yieldpoint.briefing import render
from yieldpoint.events import Event
from yieldpoint.history import History, fold, stale


def event(keys=(), checked=(), at=0) -> Event:
    return Event(surface="test", status="repair", keys=tuple(keys),
                 checked=tuple(checked), at=at)


class FoldCase(unittest.TestCase):
    def test_counts_each_rule_per_path(self):
        folded = fold([
            event(keys=("a.py::complexity_too_high", "a.py::file_too_long")),
            event(keys=("a.py::complexity_too_high", "b.py::empty_test")),
        ])
        self.assertEqual(folded["a.py"].repeats,
                         (("complexity_too_high", 2), ("file_too_long", 1)))
        self.assertEqual(folded["b.py"].repeats, (("empty_test", 1),))

    def test_ranks_commonest_first_then_alphabetically(self):
        folded = fold([event(keys=("a.py::zebra", "a.py::alpha", "a.py::alpha"))])
        self.assertEqual(folded["a.py"].repeats, (("alpha", 2), ("zebra", 1)))

    def test_checked_and_clean_is_not_the_same_as_unseen(self):
        folded = fold([event(checked=("clean.py",), at=100)])
        self.assertEqual(folded["clean.py"].repeats, ())
        self.assertEqual(folded["clean.py"].last_checked, 100)
        self.assertTrue(folded["clean.py"].seen)
        self.assertNotIn("never.py", folded)

    def test_last_checked_is_the_most_recent_not_the_last_written(self):
        folded = fold([event(checked=("a.py",), at=900),
                       event(checked=("a.py",), at=100)])
        self.assertEqual(folded["a.py"].last_checked, 900)

    def test_a_key_without_a_rule_is_ignored(self):
        self.assertEqual(fold([event(keys=("a.py",))]), {})

    def test_no_events_yields_no_history(self):
        self.assertEqual(fold([]), {})


class StaleCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.file = self.root / "a.py"
        self.file.write_text("x = 1\n")

    def test_edited_after_the_last_check(self):
        os.utime(self.file, (500, 500))
        self.assertIs(stale(History(last_checked=100), self.file), True)

    def test_unchanged_since_the_last_check(self):
        os.utime(self.file, (100, 100))
        self.assertIs(stale(History(last_checked=500), self.file), False)

    def test_a_path_never_checked_is_not_stale(self):
        """No timestamp means no comparison to make, whatever the mtime says."""
        os.utime(self.file, (10_000, 10_000))
        self.assertIs(stale(History(), self.file), False)

    def test_a_missing_file_is_not_stale(self):
        """An unreadable file is reported as not stale, never as an error."""
        self.assertIs(stale(History(last_checked=1), self.root / "gone.py"), False)


class BriefIntegrationCase(unittest.TestCase):
    """The two states that read alike, seen through an actual brief."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "a.py").write_text("x = 1\n")
        self.policy = {"project": {"name": "Demo"},
                       "structure": {"max_file_lines": 40, "max_change_lines": 200}}

    def _ledger(self, *events) -> None:
        from yieldpoint.ledger import record
        target = self.root / ".yieldpoint" / "metrics.jsonl"
        for item in events:
            record(item, target)

    def test_prior_findings_reach_the_brief(self):
        self._ledger(event(keys=("a.py::complexity_too_high",), checked=("a.py",)))
        report = brief(["a.py"], self.policy, root=self.root)
        self.assertEqual(report.files[0].repeats, (("complexity_too_high", 1),))
        self.assertIn("has tripped before: complexity_too_high x1", render(report))

    def test_a_ledger_that_never_saw_this_path_says_so(self):
        self._ledger(event(keys=("other.py::empty_test",), checked=("other.py",)))
        report = brief(["a.py"], self.policy, root=self.root)
        self.assertTrue(report.files[0].never_checked)
        self.assertIn("never analysed", render(report))

    def test_no_ledger_claims_nothing_about_history(self):
        """Absent a ledger, "never analysed" would be noise, not a finding."""
        report = brief(["a.py"], self.policy, root=self.root)
        self.assertFalse(report.files[0].never_checked)
        self.assertEqual(report.files[0].repeats, ())

    def test_a_file_edited_since_the_last_check_is_flagged(self):
        self._ledger(event(checked=("a.py",), at=1))
        os.utime(self.root / "a.py", (10_000, 10_000))
        report = brief(["a.py"], self.policy, root=self.root)
        self.assertTrue(report.files[0].unchecked)
        self.assertIn("changed since anything last analysed it", render(report))

    def test_history_survives_a_file_nothing_can_measure(self):
        (self.root / "ci.yml").write_text("on: push\n")
        self._ledger(event(keys=("ci.yml::ci_check_removed",), checked=("ci.yml",)))
        text = render(brief(["ci.yml"], self.policy, root=self.root))
        self.assertIn("not measured for this file type", text)
        self.assertIn("ci_check_removed x1", text)


if __name__ == "__main__":
    unittest.main()
