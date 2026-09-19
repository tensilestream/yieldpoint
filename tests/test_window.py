"""Selecting part of the ledger.

The ledger is append-only and has no idea what a session is, which is right for
the file and wrong for the question people ask. A session is a window of time,
so that is what this selects.
"""

from __future__ import annotations

import unittest

from aegisflow import window
from aegisflow.ledger import Event

NOW = 1_700_000_000


def _event(at=NOW, run="", agent=""):
    return Event(surface="review", status="pass", at=at, run=run, agent=agent)


class TestPeriods(unittest.TestCase):
    def test_it_reads_the_forms_people_type(self):
        for text, seconds in (("30m", 1_800), ("2h", 7_200), ("7d", 604_800),
                              ("1w", 604_800)):
            with self.subTest(text):
                self.assertEqual(window.parse(since=text, now=NOW).since,
                                 NOW - seconds)

    def test_today_is_midnight_not_a_rolling_day(self):
        chosen = window.parse(since="today", now=NOW)
        self.assertEqual(chosen.since % 86_400, 0)

    def test_an_unreadable_period_raises_rather_than_selecting_everything(self):
        """Silently widening the window would overstate every number in it."""
        with self.assertRaises(window.BadWindow):
            window.parse(since="last tuesday")

    def test_no_period_selects_everything(self):
        self.assertTrue(window.parse().everything)


class TestSelection(unittest.TestCase):
    def test_it_keeps_only_what_is_recent_enough(self):
        chosen = window.parse(since="1h", now=NOW)
        events = [_event(at=NOW - 30), _event(at=NOW - 7_200)]
        self.assertEqual(len(window.apply(events, chosen)), 1)

    def test_an_untimestamped_event_is_excluded_not_assumed_recent(self):
        """Assuming would fold old work into today's numbers."""
        chosen = window.parse(since="1h", now=NOW)
        self.assertEqual(window.apply([_event(at=0)], chosen), [])

    def test_it_selects_by_run(self):
        chosen = window.parse(run="job-1")
        events = [_event(run="job-1"), _event(run="job-2")]
        self.assertEqual(len(window.apply(events, chosen)), 1)

    def test_it_selects_by_agent(self):
        chosen = window.parse(agent="worker-3")
        events = [_event(agent="worker-3"), _event(agent="worker-9")]
        self.assertEqual(len(window.apply(events, chosen)), 1)

    def test_filters_combine(self):
        chosen = window.parse(since="1h", run="job-1", now=NOW)
        events = [
            _event(at=NOW - 30, run="job-1"),
            _event(at=NOW - 30, run="job-2"),
            _event(at=NOW - 7_200, run="job-1"),
        ]
        self.assertEqual(len(window.apply(events, chosen)), 1)

    def test_it_says_what_it_selected(self):
        self.assertIn("run job-1", window.parse(run="job-1").describe())
        self.assertEqual(window.parse().describe(), "everything recorded")


if __name__ == "__main__":
    unittest.main()
