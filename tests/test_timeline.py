"""Per-turn accounting, and getting it off the machine.

The totals answer "was this worth it". These answer "when", which is the only
way to see a trend rather than a number — and the export is what lets somebody
aggregate across a team without this package ever opening a socket.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from unittest import mock

from yieldpoint import ledger, sink, timeline
from yieldpoint.compaction import compact
from yieldpoint.core.policy import Policy


def _event(at: int, chars: int = 4000, findings: int = 1) -> ledger.Event:
    return ledger.Event(surface="review", status="repair", findings=findings,
                        analysed_chars=chars, at=at)


class TestTheFold(unittest.TestCase):
    def test_it_runs_oldest_first_whatever_order_it_is_given(self):
        rows = timeline.timeline([_event(300), _event(100), _event(200)])
        self.assertEqual([r.at for r in rows], [100, 200, 300])

    def test_cumulative_totals_accumulate(self):
        rows = timeline.timeline([_event(1, chars=4000), _event(2, chars=8000)])
        self.assertEqual([r.tokens_saved for r in rows], [1000, 2000])
        self.assertEqual([r.cum_tokens_saved for r in rows], [1000, 3000])
        self.assertEqual([r.cum_calls_saved for r in rows], [1, 2])
        self.assertEqual([r.cum_verdicts for r in rows], [1, 2])

    def test_findings_accumulate_separately_from_verdicts(self):
        rows = timeline.timeline([_event(1, findings=2), _event(2, findings=3)])
        self.assertEqual([r.cum_findings for r in rows], [2, 5])

    def test_every_row_carries_a_readable_time(self):
        row = timeline.timeline([_event(1_700_000_000)])[0]
        self.assertRegex(row.when, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
        self.assertEqual(row.to_dict()["when"], row.when)

    def test_an_empty_ledger_renders_nothing_rather_than_a_header(self):
        self.assertEqual(timeline.render(()), "")

    def test_each_repair_turn_reports_its_token_compaction(self):
        event = ledger.Event(surface="review", status="repair", findings=1,
                             analysed_chars=4000, prescription_chars=400, at=1)
        turn = timeline.timeline([event])[0]
        self.assertEqual(turn.compaction_source_tokens, 1000)
        self.assertEqual(turn.compacted_tokens, 100)
        self.assertEqual(turn.compaction_saved_tokens, 900)
        self.assertEqual(turn.compaction_ratio, 10.0)
        self.assertEqual(turn.cum_compaction_ratio, 10.0)

    def test_clean_turn_is_explicitly_not_a_compaction(self):
        turn = timeline.timeline([_event(1, chars=4000, findings=0)])[0]
        self.assertEqual(turn.compacted_tokens, 0)
        self.assertEqual(turn.compaction_ratio, 0.0)
        self.assertIn("—", timeline.render((turn,), paint=_plain()))


class TestTokenCompaction(unittest.TestCase):
    def test_small_feedback_still_has_one_estimated_token(self):
        result = compact(4, 1)
        self.assertEqual(result.source_tokens, 1)
        self.assertEqual(result.compacted_tokens, 1)
        self.assertEqual(result.saved_tokens, 0)

    def test_larger_feedback_reports_a_negative_token_delta(self):
        result = compact(4, 5)
        self.assertEqual(result.saved_tokens, -1)

    def test_an_expansion_is_not_described_as_smaller(self):
        event = ledger.Event(surface="review", status="repair", findings=1,
                             analysed_chars=4, prescription_chars=8, at=1)
        text = timeline.render(timeline.timeline([event]), paint=_plain())
        self.assertIn("2.0x larger on repair turns", text)

    def test_no_prescription_is_not_reported_as_a_saving(self):
        result = compact(4000, 0)
        self.assertFalse(result.applicable)
        self.assertEqual(result.ratio, 0.0)


class TestTheSink(unittest.TestCase):
    """The export path. Yieldpoint spawns a command; it never opens a socket."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "metrics.jsonl"
        self.out = Path(self.tmp.name) / "collected.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def _policy(self, argv):
        """The sink comes from the environment, never from the committed file."""
        import json as _json
        return mock.patch.dict(
            "os.environ", {sink.ENV_VAR: _json.dumps(list(argv))})

    def _collector(self):
        return [sys.executable, "-c",
                f"import sys;open({str(self.out)!r},'a').write(sys.stdin.read())"]

    def test_no_sink_configured_sends_nothing(self):
        with mock.patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop(sink.ENV_VAR, None)
            self.assertEqual(sink.flush(Policy(), [_event(1)], self.path), 0)

    def test_a_repository_cannot_name_the_command(self):
        """SECURITY.md: configuration must never be able to execute code.

        A committed .yieldpoint.json asking for a sink is reported and ignored,
        so cloning a hostile repository and running a turn executes nothing.
        """
        import json as _json
        import tempfile as _tf
        marker = Path(self.tmp.name) / "pwned"
        config = Path(self.tmp.name) / ".yieldpoint.json"
        config.write_text(_json.dumps({"metrics": {"sink": [
            sys.executable, "-c", f"open({str(marker)!r},'w').write('x')"]}}))
        policy = Policy.load(str(config))

        import os
        os.environ.pop(sink.ENV_VAR, None)
        self.assertEqual(sink.flush(policy, [_event(1)], self.path), 0)
        self.assertFalse(marker.exists(), "a committed config executed a command")
        self.assertTrue(any("never name a command" in w for w in policy.warnings))
        del _tf

    def test_it_sends_each_event_once(self):
        events = [_event(1), _event(2), _event(3)]
        with self._policy(self._collector()):
            self.assertEqual(sink.flush(Policy(), events, self.path), 3)
            self.assertEqual(sink.flush(Policy(), events, self.path), 0)
        self.assertEqual(len(self.out.read_text().splitlines()), 3)

    def test_what_arrives_is_one_json_object_per_line(self):
        with self._policy(self._collector()):
            sink.flush(Policy(), [_event(1), _event(2)], self.path)
        rows = [json.loads(line) for line in self.out.read_text().splitlines()]
        self.assertEqual([r["at"] for r in rows], [1, 2])
        self.assertEqual(rows[-1]["cum_verdicts"], 2)

    def test_a_later_event_is_sent_after_an_earlier_flush(self):
        with self._policy(self._collector()):
            sink.flush(Policy(), [_event(1)], self.path)
            self.assertEqual(
                sink.flush(Policy(), [_event(1), _event(2)], self.path), 1)

    def test_a_failing_command_never_raises_and_never_advances(self):
        """A collector being down must not lose the events it did not receive."""
        with self._policy([sys.executable, "-c", "import sys; sys.exit(1)"]):
            self.assertEqual(sink.flush(Policy(), [_event(1)], self.path), 0)
        self.assertFalse(sink.watermark_path(self.path).exists())
        # and once it comes back, the event is still waiting
        with self._policy(self._collector()):
            self.assertEqual(sink.flush(Policy(), [_event(1)], self.path), 1)

    def test_a_command_that_does_not_exist_is_swallowed(self):
        with self._policy(["yieldpoint-no-such-command-exists"]):
            self.assertEqual(sink.flush(Policy(), [_event(1)], self.path), 0)


class TestItStaysOffTheNetwork(unittest.TestCase):
    """The guarantee the sink design exists to protect."""

    def test_no_module_in_the_package_imports_an_http_client(self):
        banned = ("urllib.request", "http.client", "socket", "requests", "httpx")
        offenders = []
        for path in Path("yieldpoint").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for name in banned:
                if f"import {name}" in text or f"from {name}" in text:
                    offenders.append(f"{path}: {name}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()


class TestTheCostEstimate(unittest.TestCase):
    """Money is the estimate times a rate the reader states, and nothing else."""

    def test_no_rate_means_no_figure(self):
        rows = timeline.timeline([_event(1)])
        self.assertNotIn("$", timeline.panel(rows, 0.0, _plain()))

    def test_the_rate_used_is_printed_beside_the_result(self):
        rows = timeline.timeline([_event(1, chars=4_000_000)])
        text = timeline.panel(rows, 3.0, _plain())
        self.assertIn("~$3.00", text)          # 1,000,000 tokens at $3/M
        self.assertIn("$3.00 per M tokens", text)

    def test_cost_is_linear_in_tokens(self):
        self.assertAlmostEqual(timeline.cost(1_000_000, 3.0), 3.0)
        self.assertAlmostEqual(timeline.cost(500_000, 3.0), 1.5)
        self.assertEqual(timeline.cost(0, 3.0), 0.0)

    def test_a_non_numeric_rate_is_refused_rather_than_guessed(self):
        import json as _json
        config = Path(self.tmp.name) / ".yieldpoint.json"
        config.write_text(_json.dumps({"metrics": {"price_per_million": "cheap"}}))
        policy = Policy.load(str(config))
        self.assertEqual(policy.metrics.price_per_million, 0.0)
        self.assertTrue(any("not a number" in w for w in policy.warnings))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()


def _plain():
    from yieldpoint.branding import PLAIN

    return PLAIN


class TestRepeatsAreDisclosed(unittest.TestCase):
    """The total is honest arithmetic; without this it reads as distinct work."""

    def _event(self, at, files):
        return ledger.Event(surface="check", status="pass", analysed_chars=4000,
                            at=at, checked=tuple(files))

    def test_re_analysing_one_file_set_is_named(self):
        rows = timeline.timeline([self._event(n, ["t.py"]) for n in range(1, 6)])
        text = timeline.panel(rows, 0.0, _plain())
        self.assertIn("1 distinct file set(s)", text)
        self.assertIn("4 verification(s) re-analysed one already counted", text)

    def test_distinct_work_says_nothing(self):
        rows = timeline.timeline([self._event(n, [f"m{n}.py"]) for n in range(1, 4)])
        self.assertNotIn("re-analysed", timeline.panel(rows, 0.0, _plain()))

    def test_the_totals_still_count_every_verification(self):
        """Disclosure, not deduplication — a judge would have read each one."""
        rows = timeline.timeline([self._event(n, ["t.py"]) for n in range(1, 6)])
        self.assertEqual(rows[-1].cum_calls_saved, 5)
        self.assertEqual(rows[-1].cum_tokens_saved, 5000)
