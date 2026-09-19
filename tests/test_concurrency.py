"""The ledger under a fan-out.

A verifier for agent builders has to survive the way agents are actually run:
many workers, one repository, all appending at once, for hours. Three things
have to hold, and each was a real defect before it was a test.

1. Concurrent appends do not corrupt each other.
2. The running total the footer reads stays cheap as the ledger grows. It is
   read on *every* verdict, so recomputing it from the whole file is O(events
   squared) over a session.
3. Nothing in the write path reads the file in order to rewrite it.
"""

from __future__ import annotations

import concurrent.futures
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from aegisflow import ledger
from aegisflow.core.verdict import Confidence, Finding, Status, Verdict
from aegisflow.totals import totals

ROOT = Path(__file__).resolve().parent.parent

WRITER = """
import sys
sys.path.insert(0, %r)
from aegisflow import ledger
from aegisflow.core.verdict import Verdict, Finding, Status, Confidence
path, agent, rounds = sys.argv[1], sys.argv[2], int(sys.argv[3])
v = Verdict.of(
    [Finding(rule="assertion_monotonicity", status=Status.REPAIR, file="t.py",
             line=1, detail="d" * 400, prescription="p" * 400,
             confidence=Confidence.EXACT)],
    checked=["src/a/very/deeply/nested/package/module_%%d.py" %% n for n in range(60)],
)
for _ in range(rounds):
    ledger.record(ledger.observe(v, agent, analysed_chars=2048), path)
""" % str(ROOT)


def _verdict(findings: int = 1) -> Verdict:
    return Verdict.of([
        Finding(rule="assertion_monotonicity", status=Status.REPAIR, file=f"t{i}.py",
                line=1, detail="d", prescription="p", confidence=Confidence.EXACT)
        for i in range(findings)
    ], checked=[f"t{i}.py" for i in range(findings)])


class TestLineIsAtomicallyAppendable(unittest.TestCase):
    """A POSIX append is atomic only up to the pipe buffer, so lines stay small."""

    def test_a_large_verdict_still_fits(self):
        verdict = Verdict.of(
            [Finding(rule="r", status=Status.REPAIR, file="x" * 200, line=1,
                     detail="d" * 5000, prescription="p" * 5000,
                     confidence=Confidence.EXACT)],
            checked=[f"{'deep/' * 20}module_{n}.py" for n in range(400)],
        )
        line = ledger._fit(ledger.observe(verdict, "review", analysed_chars=10_000))
        self.assertLessEqual(len(line.encode("utf-8")), ledger.MAX_LINE_BYTES + 1)

    def test_trimming_never_falsifies_a_count(self):
        """A shorter path list is a smaller sample; a wrong count is a wrong number."""
        verdict = _verdict(findings=40)
        event = ledger.observe(verdict, "review", analysed_chars=9_999)
        restored = ledger.Event.from_dict(json.loads(ledger._fit(event).strip()))
        self.assertEqual(restored.findings, 40)
        self.assertEqual(restored.analysed_chars, 9_999)
        self.assertEqual(restored.files_checked, 40)


class TestConcurrentWriters(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "metrics.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_many_threads_lose_nothing(self):
        event = ledger.observe(_verdict(), "review", analysed_chars=100)
        with concurrent.futures.ThreadPoolExecutor(max_workers=32) as pool:
            list(pool.map(lambda _: ledger.record(event, self.path), range(400)))
        self.assertEqual(len(ledger.load(self.path)), 400)

    def test_separate_processes_do_not_interleave(self):
        """The real fan-out: one repository, many worker processes."""
        script = Path(self.tmp.name) / "writer.py"
        script.write_text(WRITER)
        workers = 12
        rounds = 6
        procs = [
            subprocess.Popen(
                [sys.executable, str(script), str(self.path), f"agent-{i:02d}", str(rounds)]
            )
            for i in range(workers)
        ]
        for proc in procs:
            proc.wait(timeout=120)

        lines = self.path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), workers * rounds)
        for line in lines:
            json.loads(line)  # raises here if two writes interleaved


class TestRunningTotalStaysCheap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "metrics.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def _fill(self, count: int) -> None:
        event = ledger.observe(_verdict(), "review", analysed_chars=1000)
        for _ in range(count):
            ledger.record(event, self.path)

    def test_the_total_is_correct(self):
        self._fill(50)
        running = totals(self.path)
        self.assertEqual(running.verdicts, 50)
        self.assertEqual(running.findings, 50)
        self.assertEqual(running.analysed_chars, 50_000)

    def test_it_stays_correct_as_events_are_appended(self):
        self._fill(10)
        self.assertEqual(totals(self.path).verdicts, 10)
        self._fill(15)
        self.assertEqual(totals(self.path).verdicts, 25)

    def test_it_does_not_slow_down_as_the_ledger_grows(self):
        """The footer reads this on every verdict, so it must not scale with size."""
        self._fill(200)
        totals(self.path)
        small = self._time_one()

        self._fill(4000)
        totals(self.path)
        large = self._time_one()

        self.assertLess(
            large, small * 8 + 0.005,
            f"reading the total went from {small * 1000:.2f}ms to {large * 1000:.2f}ms "
            "as the ledger grew; the fold is no longer incremental",
        )

    def _time_one(self) -> float:
        start = time.perf_counter()
        for _ in range(20):
            totals(self.path)
        return (time.perf_counter() - start) / 20

    def test_a_corrupt_cache_falls_back_rather_than_lying(self):
        self._fill(30)
        totals(self.path)
        Path(str(self.path) + ".totals.json").write_text("{not json")
        self.assertEqual(totals(self.path).verdicts, 30)

    def test_a_truncated_ledger_resets_the_cache(self):
        self._fill(30)
        totals(self.path)
        self.path.write_text("")
        self.assertEqual(totals(self.path).verdicts, 0)


class TestAgentCorrelation(unittest.TestCase):
    def test_workers_are_attributed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "m.jsonl"
            for worker in ("w1", "w1", "w2"):
                ledger.record(
                    ledger.observe(_verdict(), "review",
                                   who=ledger.Who("job-1", worker)), path
                )
            from aegisflow.stats import summarise

            summary = summarise(ledger.load(path))
            self.assertEqual(dict(summary.agents), {"w1": 2, "w2": 1})
            self.assertEqual(summary.runs, 1)


if __name__ == "__main__":
    unittest.main()


class TestAttributionIsNotSilentlyRebound(unittest.TestCase):
    """``Who(*identity())`` is positional, so field order is a contract.

    A field inserted above ``run`` rebinds every worker's label to the wrong
    column. Nothing raises and no verdict looks wrong; the attribution is just
    false from then on, which is the kind of defect that survives for months.
    """

    def test_identity_maps_onto_who_in_that_order(self):
        who = ledger.Who(*("a-run", "a-worker"))
        self.assertEqual((who.run, who.agent), ("a-run", "a-worker"))

    def test_the_environment_lands_in_the_right_columns(self):
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {"AEGISFLOW_RUN_ID": "R",
                                          "AEGISFLOW_AGENT": "A"}):
            event = ledger.observe(_verdict(), "review")
        self.assertEqual((event.run, event.agent), ("R", "A"))

    def test_who_has_exactly_the_two_fields_identity_returns(self):
        self.assertEqual(
            list(ledger.Who.__dataclass_fields__), ["run", "agent"],
            "identity() is splatted into Who; adding a field breaks attribution",
        )
