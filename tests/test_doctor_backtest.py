"""Doctor and backtest: the two commands that build trust before adoption.

Doctor exists because every silent failure mode looks identical from outside —
nothing happens, and nothing says why. Backtest exists because the question
worth answering is not "what is your false-positive rate" but "what would you
have done to my repository", and only history can answer that.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from yieldpoint import backtest, doctor

ROOT = Path(__file__).resolve().parent.parent


def _git(args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, timeout=60, check=False)


class TestDoctorFindsSilentFailures(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "a.py").write_text("x = 1\n")

    def tearDown(self):
        self.tmp.cleanup()

    def _config(self, data):
        (self.root / ".yieldpoint.json").write_text(json.dumps(data))

    def _check(self, name):
        return next(c for c in doctor.run(self.root) if c.name == name)

    def test_patterns_matching_no_file_is_a_failure(self):
        """The core rule silently never running is the worst state to be in."""
        self._config({"test_contract": {"protected_patterns": ["**/spec/**"]}})
        check = self._check("protected tests")
        self.assertEqual(check.state, doctor.FAIL)
        self.assertIn("never run", check.detail)

    def test_patterns_that_match_are_reported_ok(self):
        (self.root / "test_a.py").write_text("def test_x():\n    assert a == 1\n")
        self._config({"test_contract": {"protected_patterns": ["**/test_*.py"]}})
        self.assertEqual(self._check("protected tests").state, doctor.OK)

    def test_a_mistyped_config_key_is_a_failure_with_a_suggestion(self):
        self._config({"strcture": {"severity": "repair"}})
        check = self._check("config")
        self.assertEqual(check.state, doctor.FAIL)
        self.assertIn("structure", check.detail)

    def test_a_dead_escalate_path_is_a_warning(self):
        self._config({"routing": {"escalate_paths": ["src/payments/**"]}})
        check = self._check("escalate paths")
        self.assertEqual(check.state, doctor.WARN)
        self.assertIn("protects nothing", check.fix)

    def test_a_missing_hook_says_nothing_is_enforcing(self):
        check = self._check("hook")
        self.assertEqual(check.state, doctor.WARN)
        self.assertIn("nothing is enforcing", check.detail)

    def test_a_hook_command_that_cannot_run_is_a_failure(self):
        """The failure that presents as "installed" and verifies nothing."""
        settings = self.root / ".claude"
        settings.mkdir()
        (settings / "settings.json").write_text(json.dumps({
            "hooks": {"PreToolUse": [{"matcher": "Edit", "hooks": [
                {"type": "command", "command": "/nonexistent/yieldpoint hook"}]}]}
        }))
        check = self._check("hook")
        self.assertEqual(check.state, doctor.FAIL)
        self.assertIn("does not run", check.detail)

    def test_worst_summarises_the_run(self):
        self._config({"test_contract": {"protected_patterns": ["**/spec/**"]}})
        self.assertEqual(doctor.worst(doctor.run(self.root)), doctor.FAIL)

    def test_it_reads_and_changes_nothing(self):
        before = sorted(p.name for p in self.root.rglob("*"))
        doctor.run(self.root)
        self.assertEqual(sorted(p.name for p in self.root.rglob("*")), before)


class TestBacktest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        _git(["init", "-q", "."], self.root)
        _git(["config", "user.email", "t@example.com"], self.root)
        _git(["config", "user.name", "t"], self.root)
        (self.root / ".yieldpoint.json").write_text(json.dumps(
            {"test_contract": {"protected_patterns": ["**/test_*.py"]}}))
        self.test = self.root / "test_invoice.py"
        self.test.write_text(
            "from billing import invoice\n\ndef test_total():\n"
            "    assert invoice.total == 42\n"
        )
        self._commit("initial")

    def tearDown(self):
        self.tmp.cleanup()

    def _commit(self, message):
        _git(["add", "-A"], self.root)
        _git(["commit", "-qm", message], self.root)

    def test_a_clean_history_flags_nothing(self):
        self.test.write_text(self.test.read_text() + "\ndef test_more():\n"
                             "    assert invoice.tax == 7\n")
        self._commit("add a test")
        result = backtest.run(self.root, since="HEAD~1")
        self.assertEqual(len(result.commits), 1)
        self.assertEqual(result.contract_flagged, ())

    def test_a_weakening_commit_is_found(self):
        self.test.write_text(
            "from billing import invoice\n\ndef test_total():\n"
            "    assert invoice.total\n"
        )
        self._commit("weaken the assertion")
        result = backtest.run(self.root, since="HEAD~1")
        self.assertEqual(len(result.contract_flagged), 1)
        self.assertIn("assertion_monotonicity",
                      result.contract_flagged[0].contract_rules)

    def test_it_replays_against_the_state_at_that_commit(self):
        """Not against the working tree, which is what makes it a backtest."""
        self.test.write_text(
            "from billing import invoice\n\ndef test_total():\n"
            "    assert invoice.total\n"
        )
        self._commit("weaken")
        self.test.write_text(
            "from billing import invoice\n\ndef test_total():\n"
            "    assert invoice.total == 99\n"
        )
        self._commit("restore a strong assertion")
        result = backtest.run(self.root, since="HEAD~2")
        self.assertEqual(len(result.commits), 2)
        self.assertEqual(len(result.contract_flagged), 1,
                         "the later commit must not hide the earlier one")

    def test_outside_a_repository_it_explains(self):
        with tempfile.TemporaryDirectory() as plain:
            result = backtest.run(plain, since="HEAD~1")
        self.assertTrue(result.reason)
        self.assertEqual(result.commits, ())

    def test_the_report_separates_correctness_from_maintainability(self):
        self.test.write_text(
            "from billing import invoice\n\ndef test_total():\n"
            "    assert invoice.total\n"
        )
        self._commit("weaken")
        text = backtest.render(backtest.run(self.root, since="HEAD~1"), "HEAD~1")
        self.assertIn("CORRECTNESS", text)
        self.assertIn("MAINTAINABILITY", text)
        self.assertIn("cannot tell you which findings were", text)


if __name__ == "__main__":
    unittest.main()


class TestHookFiredCheck(unittest.TestCase):
    """Installed is not the same as running.

    A hook is read when a session starts, so one installed mid-session does
    nothing until the next — and the symptom is identical to it working: no
    output, no error, every edit allowed. This is the only check that tells
    those apart.
    """

    def setUp(self):
        # This check reads the ledger, and a test run does not record by
        # design. Force it on for these, pointed at a temporary tree.
        self._env = mock.patch.dict(os.environ, {"YIELDPOINT_METRICS": "1"})
        self._env.start()

        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "test_a.py").write_text("def test_x():\n    assert a == 1\n")
        (self.root / ".yieldpoint.json").write_text(json.dumps(
            {"test_contract": {"protected_patterns": ["**/test_*.py"]}}))
        settings = self.root / ".claude"
        settings.mkdir()
        (settings / "settings.json").write_text(json.dumps({
            "hooks": {"PreToolUse": [{"matcher": "Edit", "hooks": [
                {"type": "command", "command": "yieldpoint hook --advisory"}]}]}
        }))

    def tearDown(self):
        self._env.stop()
        self.tmp.cleanup()

    def _hook_check(self):
        return next(c for c in doctor.run(self.root) if c.name == "hook")

    def _record_surface(self, surface):
        from yieldpoint import ledger
        from yieldpoint.core.policy import Policy
        from yieldpoint.core.verdict import Verdict

        ledger.record(
            ledger.observe(Verdict.of([], checked=["test_a.py"]), surface),
            ledger.path_for(Policy.load(self.root / ".yieldpoint.json"), self.root),
        )

    def test_installed_but_never_fired_is_a_warning(self):
        check = self._hook_check()
        self.assertEqual(check.state, doctor.WARN)
        self.assertIn("never seen an edit", check.detail)
        self.assertIn("session starts", check.fix)

    def test_other_surfaces_do_not_count_as_the_hook_running(self):
        """Running `review` by hand is not the hook gating anything."""
        self._record_surface("review")
        self.assertEqual(self._hook_check().state, doctor.WARN)

    def test_once_it_has_seen_an_edit_it_reports_running(self):
        self._record_surface("hook")
        check = self._hook_check()
        self.assertEqual(check.state, doctor.OK)
        self.assertIn("running", check.detail)
        self.assertIn("1 edit(s) seen", check.detail)


class TestHtmlReport(unittest.TestCase):
    """The page is the one surface a non-engineer will look at."""

    def _page(self, events=()):
        from yieldpoint.htmlreport import Page, render
        from yieldpoint.stats import summarise

        return render(Page("Yieldpoint Report", summarise(list(events)),
                           heading="Verification Report", source="x.jsonl"))

    def _with_findings(self):
        from yieldpoint import ledger
        from yieldpoint.core.verdict import Confidence, Finding, Status, Verdict

        verdict = Verdict.of([
            Finding(rule="assertion_monotonicity", status=Status.REPAIR,
                    file="tests/test_a.py", line=1, detail="d", prescription="p",
                    confidence=Confidence.EXACT),
            Finding(rule="function_too_long", status=Status.REPAIR,
                    file="src/b.py", line=2, detail="d", prescription="p",
                    confidence=Confidence.EXACT),
        ], checked=["tests/test_a.py", "src/b.py"])
        return [ledger.observe(verdict, "hook", analysed_chars=4_000, duration_ms=3)]

    def test_it_is_self_contained_apart_from_fonts(self):
        """No server, no build step: one file you can open or attach to a PR."""
        page = self._page(self._with_findings())
        remote = [u for u in re.findall(r'https?://[^"\')\s]+', page)
                  if "fonts.g" not in u]
        self.assertEqual(remote, [], "the page must not fetch anything else")

    def test_every_colour_token_is_defined_in_the_base_theme(self):
        """A colour defined only in a media query is invisible in the third
        theme state, where nothing is stamped on the root element."""
        page = self._page(self._with_findings())
        base = re.search(r":root \{(.*?)\}", page, re.S).group(1)
        defined = set(re.findall(r"--([\w-]+):", base))
        used = set(re.findall(r"var\(--([\w-]+)\)", page))
        self.assertEqual(used - defined, set())

    def test_the_heading_does_not_repeat_the_product_name(self):
        page = self._page(self._with_findings())
        self.assertIn("<h1>Verification Report</h1>", page)

    def test_correctness_findings_are_marked_apart(self):
        """Severity has to read at a glance, not only as a number."""
        page = self._page(self._with_findings())
        self.assertIn("assertion_monotonicity", page)
        self.assertIn("correctness", page)
        self.assertIn("is-signal", page)

    def test_the_three_claim_tiers_are_all_present(self):
        page = self._page(self._with_findings())
        for tier in ("tier-measured", "tier-architectural", "tier-estimated"):
            self.assertIn(tier, page)
        self.assertIn("not claimed", page.lower())

    def test_an_empty_ledger_says_so_rather_than_showing_zeros(self):
        page = self._page([])
        self.assertIn("Nothing recorded yet", page)
        self.assertNotIn("tier-measured", page)

    def test_content_is_escaped(self):
        from yieldpoint.htmlreport import Page, render
        from yieldpoint.stats import Summary

        page = render(Page("<script>x</script>", Summary(verdicts=1),
                           scope="<b>s</b>"))
        self.assertNotIn("<script>", page)
