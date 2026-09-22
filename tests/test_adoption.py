"""How long this took to earn its place.

§10 named the metric nobody was measuring: six of the review's nine items are
about not producing *false* blocks, and none about producing a *true* finding
quickly — which is the only reason the reviewer kept it.
"""

import unittest

from yieldpoint.events import Event
from yieldpoint.adoption import ENOUGH, measure, render, to_dict

HOUR = 3_600


def _event(at, findings=0, acknowledged=0, keys=(), checked=()):
    return Event(surface="review", status="repair" if findings else "pass",
                 at=at, findings=findings, acknowledged=acknowledged,
                 keys=tuple(keys), checked=tuple(checked))


class TestFirstValue(unittest.TestCase):
    def test_it_reports_which_run_first_found_something(self):
        found = measure([_event(100), _event(200), _event(300, findings=1)])
        self.assertEqual(found.first_finding_run, 3)

    def test_it_reports_how_long_that_took(self):
        found = measure([_event(HOUR), _event(3 * HOUR, findings=1)])
        self.assertEqual(found.minutes_to_first, 120)

    def test_a_run_with_no_timestamp_is_not_counted_as_the_beginning(self):
        """Zero is the absence of a timestamp, not the epoch."""
        self.assertEqual(measure([_event(0), _event(HOUR)]).runs, 1)

    def test_a_ledger_that_never_found_anything_says_so(self):
        found = measure([_event(100), _event(200)])
        self.assertEqual(found.first_finding_run, 0)
        self.assertIn("Nothing found in", render(found))

    def test_an_empty_ledger_is_not_an_error(self):
        self.assertIn("Nothing recorded", render(measure([])))


class TestWhatHappenedNext(unittest.TestCase):
    """A fixed finding is one somebody agreed with."""

    def test_a_key_that_stops_firing_while_the_file_is_still_checked_is_fixed(self):
        found = measure([
            _event(100, findings=1, keys=["a.py::r"], checked=["a.py"]),
            _event(200, checked=["a.py"]),
        ])
        self.assertEqual((found.fixed, found.outstanding), (1, 0))

    def test_a_key_that_stops_because_nobody_looked_again_is_not_fixed(self):
        """The file was never re-examined, so nothing was demonstrated."""
        found = measure([
            _event(100, findings=1, keys=["a.py::r"], checked=["a.py"]),
            _event(200, checked=["b.py"]),
        ])
        self.assertEqual((found.fixed, found.outstanding), (0, 1))

    def test_a_key_still_firing_is_still_open(self):
        found = measure([
            _event(100, findings=1, keys=["a.py::r"], checked=["a.py"]),
            _event(200, findings=1, keys=["a.py::r"], checked=["a.py"]),
        ])
        self.assertEqual(found.outstanding, 1)

    def test_acknowledgements_are_counted_apart_from_fixes(self):
        found = measure([_event(100, findings=1, acknowledged=2)])
        self.assertEqual(found.acknowledged, 2)

    def test_the_agreed_share_is_fixes_over_everything_settled(self):
        found = measure([
            _event(100, findings=1, acknowledged=1, keys=["a.py::r"], checked=["a.py"]),
            _event(200, checked=["a.py"]),
        ])
        self.assertEqual(found.agreed, 0.5)

    def test_nothing_settled_is_not_a_zero_percent_agreement(self):
        self.assertEqual(measure([_event(100)]).agreed, 0.0)


class TestRender(unittest.TestCase):
    def _many(self, findings=1):
        events = [_event(100 + i, findings=findings if i == 1 else 0,
                         keys=["a.py::r"] if i == 1 else (), checked=["a.py"])
                  for i in range(ENOUGH + 2)]
        return render(measure(events))

    def test_a_short_history_declines_to_report_a_ratio(self):
        text = render(measure([_event(100, findings=1)]))
        self.assertIn("Too few runs", text)

    def test_a_long_enough_history_reports_one(self):
        self.assertIn("of settled findings were fixed", self._many())

    def test_it_warns_what_a_falling_share_would_mean(self):
        self.assertIn("argued with rather than used", self._many())


class TestMachineReadable(unittest.TestCase):
    def test_every_field_is_carried(self):
        payload = to_dict(measure([_event(100, findings=2, acknowledged=1)]))
        self.assertEqual(sorted(payload),
                         ["acknowledged", "findings", "first_finding_run", "fixed",
                          "minutes_to_first_finding", "outstanding", "runs"])


if __name__ == "__main__":
    unittest.main()
