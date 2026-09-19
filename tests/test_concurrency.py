"""The ledger under a fan-out.

A verifier for agent builders has to survive the way agents are actually run:
many workers, one repository, all appending at once, for hours. Three things
have to hold, and each was a real defect before it was a test.

1. Concurrent appends do not corrupt each other.
2. The running total the footer reads stays cheap as the ledger grows. It is
   read on *every* verdict, so recomputing it from the whole file is O(events
   squared) over a session.
3. Nothing in the write path reads the file in order to rewrite it.
4. The cross-process lock really excludes. Appends were lost on Windows for
   weeks because append mode there is seek-then-write, and a lost write raises
   nothing at all — so the CI failure looked like flakiness and three rounds of
   retry tuning could not have fixed it. Asserting mutual exclusion directly
   means the next such defect fails on every platform, not only the one nobody
   develops on.
"""

from __future__ import annotations

import concurrent.futures
import contextlib
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from yieldpoint import filelock, ledger
from yieldpoint.core.verdict import Confidence, Finding, Status, Verdict
from yieldpoint.totals import totals

ROOT = Path(__file__).resolve().parent.parent

WRITER = """
import sys
sys.path.insert(0, %r)
from yieldpoint import ledger
from yieldpoint.core.verdict import Verdict, Finding, Status, Confidence
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


#: Read-modify-write on a shared counter: the classic way to see a lock that is
#: not excluding. Without mutual exclusion, two processes read the same value
#: and the increments collide, so the total comes up short.
COUNTER = """
import sys, time
sys.path.insert(0, %r)
from yieldpoint import filelock
path, rounds = sys.argv[1], int(sys.argv[2])
for _ in range(rounds):
    with filelock.exclusive(path):
        with open(path) as handle:
            value = int(handle.read() or 0)
        time.sleep(0.001)          # widen the window a real race would need
        with open(path, "w") as handle:
            handle.write(str(value + 1))
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
        script.write_text(WRITER, encoding="utf-8")
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


class TestTheLockExcludes(unittest.TestCase):
    """The lock itself, separate from the ledger that depends on it."""

    def test_no_two_processes_are_inside_at_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "counter.py"
            script.write_text(COUNTER, encoding="utf-8")
            counter = Path(tmp) / "count"
            counter.write_text("0", encoding="utf-8")

            workers, rounds = 8, 5
            procs = [
                subprocess.Popen([sys.executable, str(script), str(counter), str(rounds)])
                for _ in range(workers)
            ]
            for proc in procs:
                proc.wait(timeout=120)

            self.assertEqual(int(counter.read_text()), workers * rounds)


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
        """The footer reads this on every verdict, so it must not scale with size.

        Measured in bytes handed to the fold, not in seconds. The property is
        that a read costs the size of the *new* events rather than the size of
        the ledger, and wall-clock is only a proxy for it — one that cannot tell
        a quadratic fold from a busy disk, and that failed on a shared CI runner
        while this code was correct.
        """
        self._fill(200)
        totals(self.path)                      # prime the cache
        with self._bytes_folded() as read:
            totals(self.path)
        small = sum(read)

        self._fill(4000)
        totals(self.path)                      # prime again
        with self._bytes_folded() as read:
            totals(self.path)
        large = sum(read)

        self.assertLess(
            large, small * 8 + 1,
            f"reading the total folded {small:,} bytes at 200 events and "
            f"{large:,} at 4,200; the fold is no longer incremental",
        )

    @contextlib.contextmanager
    def _bytes_folded(self):
        """How many bytes each ``totals()`` call actually handed to the fold."""
        from yieldpoint import totals as module

        seen: list[int] = []
        original = module._fold

        def spy(running, text):
            seen.append(len(text.encode("utf-8")))
            return original(running, text)

        module._fold = spy
        try:
            yield seen
        finally:
            module._fold = original

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
            from yieldpoint.stats import summarise

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

        with mock.patch.dict(os.environ, {"YIELDPOINT_RUN_ID": "R",
                                          "YIELDPOINT_AGENT": "A"}):
            event = ledger.observe(_verdict(), "review")
        self.assertEqual((event.run, event.agent), ("R", "A"))

    def test_who_has_exactly_the_two_fields_identity_returns(self):
        self.assertEqual(
            list(ledger.Who.__dataclass_fields__), ["run", "agent"],
            "identity() is splatted into Who; adding a field breaks attribution",
        )
