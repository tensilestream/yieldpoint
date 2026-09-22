"""What this has found over time, split by who caused it.

Review item #8. The reason it matters is not the chart: an individual installs
a tool, and the person who decides it stays is usually someone else looking at
it occasionally. Totals cannot answer "is this repository getting better".
"""

import unittest

from yieldpoint.events import Event
from yieldpoint.trend import Period, periods, render, to_dict

#: 2026-09-14 is a Monday; 2026-09-21 is the Monday after.
MONDAY = 1_789_344_000
DAY = 86_400


def _event(at, findings=0, inherited=0, acknowledged=0):
    return Event(surface="review", status="repair" if findings else "pass",
                 at=at, findings=findings, inherited=inherited,
                 acknowledged=acknowledged)


class TestBucketing(unittest.TestCase):
    def test_days_in_one_week_land_in_one_row(self):
        rows = periods([_event(MONDAY), _event(MONDAY + 3 * DAY),
                        _event(MONDAY + 6 * DAY)])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].turns, 3)

    def test_the_next_week_is_its_own_row(self):
        rows = periods([_event(MONDAY), _event(MONDAY + 7 * DAY)])
        self.assertEqual([r.turns for r in rows], [1, 1])

    def test_rows_are_oldest_first(self):
        rows = periods([_event(MONDAY + 7 * DAY), _event(MONDAY)])
        self.assertEqual([r.starting for r in rows],
                         ["2026-09-14", "2026-09-21"])

    def test_a_week_with_no_verification_is_not_invented(self):
        rows = periods([_event(MONDAY), _event(MONDAY + 21 * DAY)])
        self.assertEqual(len(rows), 2)

    def test_an_event_with_no_timestamp_is_skipped(self):
        self.assertEqual(periods([_event(0, findings=3)]), [])


class TestTheSplit(unittest.TestCase):
    def test_introduced_is_what_was_not_inherited(self):
        rows = periods([_event(MONDAY, findings=5, inherited=2)])
        self.assertEqual((rows[0].introduced, rows[0].inherited), (3, 2))

    def test_a_classified_turn_with_no_inherited_findings_reads_as_zero(self):
        rows = periods([_event(MONDAY, findings=4, inherited=0)])
        self.assertEqual((rows[0].introduced, rows[0].unclassified), (4, 0))

    def test_an_unclassified_turn_is_neither_introduced_nor_inherited(self):
        """Adding it to either column would be inventing history."""
        rows = periods([Event(surface="review", status="repair", at=MONDAY,
                              findings=6, inherited=None)])
        self.assertEqual((rows[0].introduced, rows[0].inherited), (0, 0))
        self.assertEqual(rows[0].unclassified, 6)

    def test_acknowledgements_are_counted_per_week(self):
        rows = periods([_event(MONDAY, acknowledged=2),
                        _event(MONDAY + DAY, acknowledged=3)])
        self.assertEqual(rows[0].acknowledged, 5)


class TestRender(unittest.TestCase):
    def test_an_empty_ledger_says_so(self):
        self.assertIn("Nothing recorded yet", render([]))

    def test_an_unclassified_week_shows_a_dash_not_a_zero(self):
        text = render(periods([Event(surface="review", status="repair",
                                     at=MONDAY, findings=6, inherited=None)]))
        self.assertIn("—", text)
        self.assertIn("never folded into either column", text)

    def test_it_reports_the_direction_once_two_weeks_are_classified(self):
        text = render(periods([_event(MONDAY, findings=9, inherited=1),
                               _event(MONDAY + 7 * DAY, findings=3, inherited=1)]))
        self.assertIn("gone down, 8 to 2", text)

    def test_a_rise_is_reported_as_a_rise(self):
        text = render(periods([_event(MONDAY, findings=2, inherited=0),
                               _event(MONDAY + 7 * DAY, findings=9, inherited=0)]))
        self.assertIn("gone up, 2 to 9", text)

    def test_flat_is_reported_as_flat_rather_than_as_improvement(self):
        text = render(periods([_event(MONDAY, findings=4, inherited=0),
                               _event(MONDAY + 7 * DAY, findings=4, inherited=0)]))
        self.assertIn("flat at 4", text)

    def test_one_classified_week_is_not_enough_to_claim_a_direction(self):
        text = render(periods([_event(MONDAY, findings=4, inherited=0)]))
        self.assertIn("Not enough classified history", text)

    def test_unclassified_weeks_do_not_count_towards_a_direction(self):
        """A split invented from history that has none is worse than silence."""
        text = render(periods([
            Event(surface="review", status="repair", at=MONDAY, findings=9,
                  inherited=None),
            _event(MONDAY + 7 * DAY, findings=3, inherited=1)]))
        self.assertIn("Not enough classified history", text)


class TestMachineReadable(unittest.TestCase):
    def test_every_column_is_carried(self):
        payload = to_dict(periods([_event(MONDAY, findings=5, inherited=2,
                                          acknowledged=1)]))
        self.assertEqual(payload["weeks"][0],
                         {"starting": "2026-09-14", "turns": 1, "found": 5,
                          "introduced": 3, "inherited": 2, "acknowledged": 1,
                          "unclassified": 0})


if __name__ == "__main__":
    unittest.main()
