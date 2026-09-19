"""When to stop and commit.

``change_too_large`` is a true finding that arrives too late to act on: by the
time it fires, splitting means unpicking thousands of lines. An agent working
for hours needs the same judgement one turn at a time, while stopping is still
cheap. These pin the order the two inputs are considered in, because that order
is the whole design.
"""

from __future__ import annotations

import unittest

from aegisflow.core.verdict import Confidence, Finding, Status, Verdict
from aegisflow.harness.pacing import COMMIT_AT, PACE, bar, pace

LIMIT = 1_000


def _verdict(*rules):
    return Verdict.of([
        Finding(rule=rule, status=Status.REPAIR, file="t.py", line=1,
                detail="d", prescription="p", confidence=Confidence.EXACT)
        for rule in rules
    ])


class TestSizeAlone(unittest.TestCase):
    def test_early_in_a_task_it_says_keep_going(self):
        self.assertEqual(pace(_verdict(), 120, 3, LIMIT).value, "continue")

    def test_approaching_the_limit_it_says_wrap_up(self):
        decision = pace(_verdict(), int(LIMIT * COMMIT_AT) + 10, 8, LIMIT)
        self.assertEqual(decision.value, "wrap-up")
        self.assertIn("Finish the current piece", decision.reason)

    def test_past_the_limit_it_is_overdue_not_a_stop(self):
        decision = pace(_verdict(), LIMIT * 4, 50, LIMIT)
        self.assertEqual(decision.value, "overdue")
        self.assertIn("Finish what you are on", decision.reason)

    def test_no_configured_limit_means_no_opinion_about_size(self):
        self.assertEqual(pace(_verdict(), 99_999, 400, 0).value, "continue")


class TestItNeverSaysStopWhereYouAre(unittest.TestCase):
    """The distinction the whole module rests on.

    Interrupting an agent halfway through a function to enforce a line budget
    leaves the repository in a worse state than letting it finish: the limit is
    about what a human can review, and half-written code is not reviewable at
    any length. So every size verdict is phrased against the next boundary.
    """

    def test_no_size_verdict_tells_anyone_to_stop_immediately(self):
        for added in (120, int(LIMIT * 0.8), LIMIT * 4, LIMIT * 40):
            with self.subTest(added=added):
                reason = pace(_verdict(), added, 9, LIMIT).reason.lower()
                for phrase in ("stop now", "stop immediately", "split it",
                               "do not continue", "abandon"):
                    self.assertNotIn(phrase, reason)

    def test_the_advice_is_always_about_the_next_boundary(self):
        for added in (int(LIMIT * 0.8), LIMIT * 4):
            with self.subTest(added=added):
                self.assertIn("finish", pace(_verdict(), added, 9, LIMIT).reason.lower())

    def test_it_is_a_choice_not_a_gate(self):
        """A Gate can deny; a Choice cannot. The type carries the guarantee."""
        from aegisflow.harness.decisions import Choice, Gate

        decision = pace(_verdict(), LIMIT * 4, 50, LIMIT)
        self.assertIsInstance(decision, Choice)
        self.assertNotIsInstance(decision, Gate)

    def test_pacing_does_not_change_the_exit_code(self):
        """Being over budget must never fail a command."""
        from aegisflow.commands import _exit_for

        clean = _verdict()
        self.assertEqual(pace(clean, LIMIT * 9, 90, LIMIT).value, "overdue")
        self.assertEqual(_exit_for(clean), 0)


class TestCorrectnessComesFirst(unittest.TestCase):
    """A weakened suite is not a good commit at any size."""

    def test_a_tiny_but_broken_change_wants_attention_first(self):
        decision = pace(_verdict("assertion_monotonicity"), 10, 1, LIMIT)
        self.assertEqual(decision.value, "fix-first")
        self.assertIn("before the next turn builds", decision.reason)

    def test_it_outranks_the_commit_threshold(self):
        decision = pace(_verdict("empty_test"), int(LIMIT * 0.9), 20, LIMIT)
        self.assertEqual(decision.value, "fix-first")

    def test_it_outranks_the_split_threshold(self):
        decision = pace(_verdict("dangling_reference"), LIMIT * 5, 90, LIMIT)
        self.assertEqual(decision.value, "fix-first")

    def test_maintainability_findings_do_not_raise_the_urgency(self):
        """Taste is not correctness; a long function can wait for the boundary."""
        decision = pace(_verdict("function_too_long"), 120, 3, LIMIT)
        self.assertEqual(decision.value, "continue")

    def test_it_names_the_rule_that_stopped_it(self):
        decision = pace(_verdict("assertion_monotonicity"), 10, 1, LIMIT)
        self.assertIn("assertion_monotonicity", decision.reason)


class TestTheDecisionIsUsable(unittest.TestCase):
    def test_every_value_is_in_the_declared_set(self):
        for verdict, added in ((_verdict(), 10), (_verdict(), LIMIT * 3),
                               (_verdict("empty_test"), 10)):
            with self.subTest(added=added):
                self.assertIn(pace(verdict, added, 2, LIMIT).value, PACE)

    def test_it_carries_the_numbers_it_decided_from(self):
        signals = pace(_verdict(), 600, 7, LIMIT).signals
        self.assertEqual(signals["added_lines"], 600)
        self.assertEqual(signals["limit"], LIMIT)
        self.assertAlmostEqual(signals["budget_used"], 0.6)

    def test_the_gauge_marks_going_over(self):
        self.assertIn("OVER", bar(pace(_verdict(), LIMIT * 2, 30, LIMIT)))
        self.assertNotIn("OVER", bar(pace(_verdict(), 100, 2, LIMIT)))


if __name__ == "__main__":
    unittest.main()


class TestItReachesTheSurfaces(unittest.TestCase):
    """Advice nobody sees is advice nobody takes."""

    def test_the_mcp_review_tool_carries_it(self):
        from aegisflow.core.policy import Policy
        from aegisflow.mcp.tools import call

        _text, structured, is_error = call("aegis_review", {}, Policy.load(None))
        self.assertFalse(is_error)
        if "pace" in structured:      # a clean tree has nothing to pace
            self.assertIn(structured["pace"]["value"], PACE)

    def test_the_html_report_shows_the_gauge_without_demanding_a_stop(self):
        from aegisflow.htmlreport import Now, Page, render
        from aegisflow.stats import Summary

        decision = pace(_verdict(), LIMIT * 3, 40, LIMIT)
        page = render(Page("t", Summary(verdicts=1), now=Now(pace=decision)))
        self.assertIn("overdue", page)
        self.assertIn("is-over", page)
        self.assertIn("Finish what you are on", page)
        self.assertNotIn("stop now", page.lower())
