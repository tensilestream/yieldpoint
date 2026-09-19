"""The ledger and its report.

Two properties matter more than the arithmetic. Recording must never be able to
break a verification, and the report must never present an estimate as a
measurement — the second is what separates this from a marketing number.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from yieldpoint import ledger
from yieldpoint.core.policy import Policy
from yieldpoint.core.verdict import Confidence, Finding, Status, Verdict
from yieldpoint.report import render, to_dict
from yieldpoint.stats import summarise


def _verdict(rules=("assertion_monotonicity",)):
    return Verdict.of([
        Finding(rule=rule, status=Status.REPAIR, file="t.py", line=1,
                detail="d", prescription="restore the assertion",
                confidence=Confidence.EXACT)
        for rule in rules
    ], checked=["t.py"])


class TestObserve(unittest.TestCase):
    def test_it_counts_what_the_verdict_holds(self):
        event = ledger.observe(_verdict(), "review", analysed_chars=400, duration_ms=7)
        self.assertEqual(event.surface, "review")
        self.assertEqual(event.status, "repair")
        self.assertEqual(event.findings, 1)
        self.assertEqual(event.rules, ("assertion_monotonicity",))
        self.assertEqual(event.analysed_chars, 400)
        self.assertGreater(event.prescription_chars, 0)

    def test_it_reads_no_clock_and_touches_no_disk(self):
        """observe() is pure; the clock is the caller's problem (RULES.md 4)."""
        first = ledger.observe(_verdict(), "check", analysed_chars=10)
        second = ledger.observe(_verdict(), "check", analysed_chars=10)
        self.assertEqual(first, second)


class TestRecording(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "nested" / "metrics.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_it_creates_the_directory_and_appends(self):
        for _ in range(3):
            self.assertTrue(ledger.record(ledger.observe(_verdict(), "hook"), self.path))
        self.assertEqual(len(ledger.load(self.path)), 3)

    def test_an_unwritable_path_is_swallowed(self):
        """Bookkeeping must never fail a verification."""
        self.assertFalse(
            ledger.record(ledger.observe(_verdict(), "hook"), Path("/proc/nope/x.jsonl"))
        )

    def test_a_damaged_line_does_not_lose_the_rest(self):
        ledger.record(ledger.observe(_verdict(), "hook"), self.path)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write("{not json\n")
        ledger.record(ledger.observe(_verdict(), "hook"), self.path)
        self.assertEqual(len(ledger.load(self.path)), 2)

    def test_a_missing_file_reads_as_no_events(self):
        self.assertEqual(ledger.load(Path(self.tmp.name) / "absent.jsonl"), [])


class TestSwitchingItOff(unittest.TestCase):
    def test_policy_disables_it(self):
        self.assertFalse(ledger.enabled(Policy.load({"metrics": {"enabled": False}})))

    def test_policy_still_wins_when_metrics_are_forced_on(self):
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {"YIELDPOINT_METRICS": "1"}):
            # A forced-on switch is about context, not about consent: a project
            # that turned recording off in its committed policy stays off.
            self.assertFalse(
                ledger.enabled(Policy.load({"metrics": {"enabled": False}})))

    def test_it_is_on_by_default(self):
        """Outside a test run, with nothing configured, it records.

        Patched on ``recording``, not on ``ledger``: the name is re-exported
        from there for callers' convenience, and ``enabled`` resolves it in its
        own module. Patching the re-export changes nothing.
        """
        from unittest import mock

        from yieldpoint import recording

        with mock.patch.object(recording, "under_test", return_value=False):
            self.assertTrue(ledger.enabled(Policy()))

    def test_the_environment_variable_wins(self):
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {"YIELDPOINT_NO_METRICS": "1"}):
            self.assertFalse(ledger.enabled(Policy()))


class TestReportHonesty(unittest.TestCase):
    """The report's whole value is that its three kinds of number stay apart."""

    def setUp(self):
        self.summary = summarise([
            ledger.observe(_verdict(), "review", analysed_chars=4000, duration_ms=5),
            ledger.observe(_verdict(("empty_test",)), "hook", analysed_chars=2000,
                           duration_ms=9),
        ])

    def test_measured_counts_are_exact(self):
        self.assertEqual(self.summary.verdicts, 2)
        self.assertEqual(self.summary.findings, 2)
        self.assertEqual(self.summary.analysed_chars, 6000)

    def test_model_calls_made_is_always_zero(self):
        self.assertEqual(to_dict(self.summary)["architectural"]["model_calls_made"], 0)

    def test_the_estimate_states_its_assumption(self):
        estimated = to_dict(self.summary)["estimated"]
        self.assertIn("characters per token", estimated["assumption"])
        self.assertEqual(
            estimated["llm_judge_input_tokens"], 6000 // ledger.CHARS_PER_TOKEN
        )

    def test_the_text_labels_every_block(self):
        text = render(self.summary)
        for heading in ("MEASURED", "ARCHITECTURAL", "ESTIMATED", "NOT CLAIMED"):
            self.assertIn(heading, text)

    def test_it_refuses_to_claim_fewer_total_model_calls(self):
        """PLAN section 4.1: unbenchmarked, so it must not appear as a result."""
        self.assertIn("does not exist yet", render(self.summary))
        self.assertTrue(to_dict(self.summary)["not_claimed"])

    def test_an_empty_ledger_says_so_rather_than_showing_zeros(self):
        text = render(summarise([]))
        self.assertIn("No verifications recorded yet", text)
        self.assertNotIn("ARCHITECTURAL", text)


if __name__ == "__main__":
    unittest.main()


class TestCompactionWording(unittest.TestCase):
    """A ratio below one must not be reported as "0x smaller"."""

    def _summary(self, analysed):
        return summarise([ledger.observe(_verdict(), "review", analysed_chars=analysed)])

    def test_a_large_change_reports_compaction(self):
        text = render(self._summary(100_000))
        self.assertIn("smaller than the code it describes", text)

    def test_a_tiny_change_says_the_critique_is_larger(self):
        text = render(self._summary(20))
        self.assertIn("larger than the code analysed", text)
        self.assertNotIn("0.0x smaller", text)


class TestItDoesNotPolluteTheRepository(unittest.TestCase):
    def test_the_ledger_directory_ignores_itself(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".yieldpoint" / "metrics.jsonl"
            ledger.record(ledger.observe(_verdict(), "hook"), path)
            marker = path.parent / ".gitignore"
            self.assertTrue(marker.is_file(), "must not need a manual .gitignore entry")
            self.assertEqual(marker.read_text().strip(), "*")

    def test_it_does_not_edit_a_gitignore_the_project_owns(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".gitignore").write_text("__pycache__/\n")
            ledger.record(ledger.observe(_verdict(), "hook"),
                          root / ".yieldpoint" / "metrics.jsonl")
            self.assertEqual((root / ".gitignore").read_text(), "__pycache__/\n")


class TestATestRunRecordsNothing(unittest.TestCase):
    """A project's own suite must not write into its own metrics.

    The failure is silent: the numbers simply drift, running the suite twice
    changes them, and running it in CI corrupts them for everyone. Nothing
    says why, which is what makes it worth detecting rather than leaving each
    project to remember.
    """

    def test_this_very_suite_is_detected_as_a_test_run(self):
        self.assertTrue(ledger.under_test())

    def test_and_therefore_recording_is_off(self):
        self.assertFalse(ledger.enabled(Policy()))

    def test_pytest_is_detected_by_its_own_variable(self):
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {"PYTEST_CURRENT_TEST": "t::x (call)"}):
            self.assertTrue(ledger.under_test())

    def test_a_real_run_still_records(self):
        """Detection must not extend to CI actually verifying a change."""
        import os
        import sys
        from unittest import mock

        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch.dict(sys.modules, {"__main__": _NotATest()}):
            self.assertFalse(ledger.under_test())
            self.assertTrue(ledger.enabled(Policy()))

    def test_it_can_be_forced_back_on(self):
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {"YIELDPOINT_METRICS": "1"}):
            self.assertTrue(ledger.enabled(Policy()))

    def test_no_metrics_still_wins_over_forcing_it_on(self):
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {"YIELDPOINT_METRICS": "1",
                                          "YIELDPOINT_NO_METRICS": "1"}):
            self.assertFalse(ledger.enabled(Policy()))


class _NotATest:
    """Stands in for a ``__main__`` that is not a test runner."""

    __spec__ = None
