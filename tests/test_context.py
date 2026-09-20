"""Compaction preserves tool data and reports only observable reductions."""
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

from yieldpoint.cli import main
from yieldpoint.context import compact_json
from yieldpoint.contextrecording import compact_and_record
from yieldpoint.contextstats import summarise as context_summary
from yieldpoint.core.policy import Policy
from yieldpoint.ledger import Event, load, record
from yieldpoint.mcp.server import handle
from yieldpoint.stats import summarise
from yieldpoint.timeline import timeline
from yieldpoint.totals import totals


class TestCompaction(unittest.TestCase):
    def test_preserves_arbitrary_tool_data(self):
        value = {"content": [{"type": "text", "text": 'Keep  spaces\n"quotes" \\ path 🐍'}],
                 "structuredContent": {"items": [None, False, 123, {"x": "a b"}]}, "isError": True}
        source = json.dumps(value, indent=4, ensure_ascii=False)
        result = compact_json(source)
        self.assertEqual(json.loads(result.text), value)
        self.assertLess(result.output_bytes, result.input_bytes)
        self.assertEqual(result.output_bytes, len(result.text.encode("utf-8")))
        self.assertEqual(result.output_chars, len(result.text))
        self.assertNotEqual(result.output_chars, result.output_bytes)

    def test_preserves_number_lexemes_and_duplicate_keys(self):
        source = '{ "x": 1.234567890123456789, "x": 1e999, "z": -0, "n": 999999999999999999999 }'
        self.assertEqual(compact_json(source).text, source.replace(" ", ""))

    def test_noop_is_not_a_saving_and_operation_is_idempotent(self):
        result = compact_json('{"x":1}')
        self.assertEqual(result.input_tokens, result.output_tokens)
        self.assertEqual(compact_json(result.text), result)

    def test_invalid_json_is_refused(self):
        for source in ('', '{', '{"x": NaN}', '[Infinity]', '{"x":1,}', '1 2', '{/*comment*/}'):
            with self.subTest(source=source), self.assertRaises(ValueError):
                compact_json(source)

    def test_exact_tokenizer_counts_are_distinct_from_estimates(self):
        result = compact_json('[  1,  2 ]', count_tokens=lambda s: len(s.encode()), tokenizer="test-byte-counter")
        self.assertEqual(result.input_tokens, result.input_bytes)
        self.assertEqual(result.output_tokens, result.output_bytes)
        self.assertEqual(result.tokenizer, "test-byte-counter")

    def test_token_expansion_retains_original(self):
        source = '[ 1 ]'
        result = compact_json(source, count_tokens=lambda s: 1 if s == source else 2, tokenizer="fixture")
        self.assertEqual(result.text, source)
        self.assertEqual(result.output_tokens, result.input_tokens)

    def test_bad_tokenizer_counts_and_unlabelled_counts_rejected(self):
        for bad in (-1, 1.5, True):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                compact_json('[]', count_tokens=lambda s: bad, tokenizer="fixture")
        with self.assertRaises(ValueError):
            compact_json('[]', count_tokens=len)


class AccountingFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / '.yieldpoint/metrics.jsonl'
        self.env = patch.dict(os.environ, {"YIELDPOINT_METRICS": "1", "YIELDPOINT_RUN_ID": "run-a",
                                          "YIELDPOINT_AGENT": "agent-a"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.policy = Policy()


class TestAccounting(AccountingFixture):
    def test_roundtrip_counts_output_without_logging_content(self):
        result, recorded = compact_and_record('{ "secret": "do not log me" }', root=self.root, policy=self.policy)
        self.assertTrue(recorded)
        self.assertNotIn('do not log me', self.path.read_text())
        events = load(self.path)
        self.assertEqual(events[0].context, result.metrics())
        self.assertEqual((events[0].run, events[0].agent), ('run-a', 'agent-a'))
        summary = summarise(events)
        self.assertEqual(summary.verdicts, 0)
        self.assertEqual(summary.context['operations'], 1)
        self.assertIsNone(summary.context['provider_tokens_saved'])
        self.assertEqual(timeline(events), ())
        self.assertEqual(totals(self.path).verdicts, 0)

    def test_mixed_ledger_does_not_inflate_checks(self):
        record(Event('review', 'pass', analysed_chars=100), self.path)
        compact_and_record('[ 1, 2 ]', root=self.root, policy=self.policy)
        events = load(self.path)
        self.assertEqual(summarise(events).verdicts, 1)
        self.assertEqual(len(timeline(events)), 1)
        self.assertEqual(totals(self.path).verdicts, 1)

    def test_estimates_and_tokenizers_are_separate(self):
        compact_and_record('[ 1, 2 ]', root=self.root, policy=self.policy)
        for name in ('counter-a', 'counter-b'):
            compact_and_record('[ 1, 2 ]', root=self.root, policy=self.policy,
                               count_tokens=len, tokenizer=name)
        data = context_summary(load(self.path), 3.0)
        self.assertEqual(data['operations'], 3)
        self.assertEqual(data['estimated']['operations'], 1)
        self.assertEqual(set(data['measured_tokens_by_tokenizer']), {'counter-a', 'counter-b'})
        self.assertEqual(data['estimated']['potential_input_cost_reduction'],
                         data['estimated']['tokens_removed'] * 3 / 1_000_000)

    def test_no_record_when_metrics_disabled(self):
        policy = Policy.from_dict({'metrics': {'enabled': False}})
        result, recorded = compact_and_record('[ 1 ]', root=self.root, policy=policy)
        self.assertEqual(result.text, '[1]')
        self.assertFalse(recorded)
        self.assertFalse(self.path.exists())

    def test_root_policy_is_respected(self):
        """A policy found on disk disables recording without disabling compaction."""
        (self.root / '.yieldpoint.json').write_text('{"metrics":{"enabled":false}}')
        result, recorded = compact_and_record('[ 1, 2 ]', root=self.root)
        self.assertEqual(result.text, '[1,2]')
        self.assertEqual(result.input_chars, 8)
        self.assertEqual(result.output_chars, 5)
        self.assertIs(recorded, False)
        self.assertFalse(self.path.exists())

    def test_cli_and_stats_are_end_to_end(self):
        with patch('sys.stdin', io.StringIO('[ 1, 2 ]')), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['compact', '--root', str(self.root)]), 0)
        self.assertEqual(output.getvalue(), '[1,2]')
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['stats', '--root', str(self.root), '--json', '--price', '3']), 0)
        data = json.loads(output.getvalue())
        self.assertEqual(data['measured']['verdicts'], 0)
        self.assertEqual(data['context_compaction']['operations'], 1)
        self.assertEqual(data['context_compaction']['estimated']['price_per_million'], 3)
        self.assertEqual(len(load(self.path)), 1)  # reading stats never records work

    def test_cli_invalid_input_has_no_output_or_record(self):
        with patch('sys.stdin', io.StringIO('bad')), redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()):
            self.assertEqual(main(['compact', '--root', str(self.root)]), 2)
        self.assertEqual(out.getvalue(), '')
        self.assertFalse(self.path.exists())

    def test_mcp_returns_only_compacted_output_and_records_it(self):
        request = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {
            'name': 'yieldpoint_compact', 'arguments': {'text': '[ 1, 2 ]', 'root': str(self.root)}}}
        result = handle(json.dumps(request), self.policy)['result']
        self.assertFalse(result['isError'])
        self.assertEqual(result['content'], [{'type': 'text', 'text': '[1,2]'}])
        self.assertNotIn('structuredContent', result)
        self.assertEqual(len(load(self.path)), 1)

    def test_corrupt_record_does_not_destroy_valid_accounting(self):
        compact_and_record('[ 1 ]', root=self.root, policy=self.policy)
        with self.path.open('a') as stream:
            stream.write('{"surface":"review","status":"pass","findings":"bad"}\n')
        self.assertEqual(context_summary(load(self.path))['operations'], 1)


class TestLedgerConsistency(AccountingFixture):
    def test_rotated_ledger_agrees_with_full_stats(self):
        record(Event('review', 'pass', analysed_chars=20), self.path)
        self.assertEqual(totals(self.path).verdicts, 1)
        self.path.replace(Path(str(self.path) + '.1'))
        self.assertEqual(totals(self.path).verdicts, 1)
        record(Event('review', 'repair', analysed_chars=30, findings=1), self.path)
        compact_and_record('[ 1 ]', root=self.root, policy=self.policy)
        measured = summarise(load(self.path))
        running = totals(self.path)
        self.assertEqual(running.verdicts, measured.verdicts)
        self.assertEqual(running.analysed_chars, measured.analysed_chars)
        self.assertEqual(totals(self.path), running)

    def test_replaced_ledger_invalidates_cache(self):
        record(Event('review', 'pass', analysed_chars=20), self.path)
        totals(self.path)
        other = self.root / 'replacement'
        record(Event('review', 'pass', analysed_chars=99), other)
        other.replace(self.path)
        self.assertEqual(totals(self.path).analysed_chars, 99)

    def test_corrupt_and_partial_rows_do_not_inflate_totals(self):
        record(Event('review', 'pass', analysed_chars=20), self.path)
        with self.path.open('a') as stream:
            stream.write('{}\n{"surface":"review","status":"pass","findings":-1}\n')
            stream.write('{"surface":"review","status":"pass","findings":"bad"}\n')
            stream.write('{"surface":"review","status":"pass"}')
        self.assertEqual(len(load(self.path)), 1)
        self.assertEqual(totals(self.path).verdicts, 1)
        with self.path.open('a') as stream:
            stream.write('\n')
        self.assertEqual(len(load(self.path)), 2)
        self.assertEqual(totals(self.path).verdicts, 2)

    def test_export_keeps_compactions(self):
        compact_and_record('[ 1 ]', root=self.root, policy=self.policy)
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(['export', '--root', str(self.root)]), 0)
        row = json.loads(out.getvalue())
        self.assertEqual(row['kind'], 'compaction')
        self.assertEqual(row['context']['output_chars'], 3)

    def test_html_and_json_use_the_same_price_and_compaction(self):
        compact_and_record('[ 1 ]', root=self.root, policy=self.policy)
        page = self.root / 'report.html'
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(['stats', '--root', str(self.root), '--html', str(page), '--price', '7']), 0)
        self.assertIn('$7/M', page.read_text())
        self.assertIn('1 operations', page.read_text())

    def test_bad_price_is_rejected_without_nan_json(self):
        for price in ('nan', 'inf', '-1'):
            with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()):
                self.assertEqual(main(['stats', '--root', str(self.root), '--json', '--price', price]), 2)
            self.assertEqual(out.getvalue(), '')

    def test_real_verification_detects_repair_and_records_resolution(self):
        before = self.root / 'before.py'
        after = self.root / 'after.py'
        strong = 'def test_total(inv):\n    assert inv.total == 42\n'
        before.write_text(strong)
        after.write_text('def test_total(inv):\n    assert inv.total is not None\n')
        args = ['check', '--path', 'tests/test_total.py', '--before', str(before),
                '--after', str(after), '--root', str(self.root), '--json']
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(args), 1)
        self.assertEqual(json.loads(out.getvalue())['findings'][0]['rule'], 'assertion_monotonicity')
        after.write_text(strong)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(args), 0)
        events = load(self.path)
        self.assertEqual(len(events), 2)
        summary = summarise(events)
        self.assertEqual(summary.verdicts, 2)
        self.assertEqual(summary.resolved, 1)
        self.assertEqual(summary.context['operations'], 0)

    def test_diff_command_records_real_check(self):
        (self.root / 'tests').mkdir()
        (self.root / 'tests/test_total.py').write_text('def test_total(inv):\n    assert inv.total is not None\n')
        diff = '--- a/tests/test_total.py\n+++ b/tests/test_total.py\n@@ -1,2 +1,2 @@\n def test_total(inv):\n-    assert inv.total == 42\n+    assert inv.total is not None\n'
        with patch('sys.stdin', io.StringIO(diff)), redirect_stdout(io.StringIO()):
            self.assertEqual(main(['check', '--diff', '-', '--root', str(self.root), '--json']), 1)
        events = load(self.path)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].surface, 'check:diff')
        self.assertEqual(events[0].analysed_chars, len(diff))


if __name__ == '__main__':
    unittest.main()
