"""The gate that does not depend on which tool made the edit.

Every test here is about the same hole: a ``PreToolUse`` hook verifies a tool
call, so an agent that edits through the shell is invisible to it. These assert
that the Stop gate closes that hole, and that closing it cannot trap an agent in
a loop.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from yieldpoint import stop
from yieldpoint.core.policy import Policy

ROOT = Path(__file__).resolve().parent.parent

ORIGINAL = (
    "import unittest\n\n\n"
    "class TestInvoice(unittest.TestCase):\n"
    "    def test_total(self):\n"
    "        inv = build()\n"
    "        self.assertEqual(inv.total, 42)\n"
    '        self.assertEqual(inv.currency, "USD")\n'
)
WEAKENED = ORIGINAL.replace(
    'self.assertEqual(inv.currency, "USD")', "self.assertTrue(inv.currency)"
)


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


class _Repository:
    """A real git repository, because this gate's whole input is a git diff."""

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)
        (self.path / "tests").mkdir()
        self.test = self.path / "tests" / "test_invoice.py"
        self.test.write_text(ORIGINAL, encoding="utf-8")
        _git("init", "-q", ".", cwd=self.path)
        _git("config", "user.email", "t@t", cwd=self.path)
        _git("config", "user.name", "t", cwd=self.path)
        _git("add", "-A", cwd=self.path)
        _git("commit", "-qm", "init", cwd=self.path)
        return self

    def __exit__(self, *exc):
        from yieldpoint.core import parsecache
        parsecache.close()
        self.tmp.cleanup()

    def weaken(self):
        """Edit the file directly — the shell's way, which no tool payload shows."""
        self.test.write_text(WEAKENED, encoding="utf-8")


class TestItSeesWhatThePerEditHookCannot(unittest.TestCase):
    def test_a_weakening_written_outside_any_tool_is_caught(self):
        with _Repository() as repo:
            repo.weaken()
            outcome = stop.evaluate(repo.path, Policy())
            self.assertTrue(outcome.ran)
            self.assertTrue(outcome.holds)
            self.assertEqual(
                [f.rule for f in outcome.verdict.findings], ["assertion_monotonicity"]
            )

    def test_an_untouched_tree_holds_nothing(self):
        with _Repository() as repo:
            outcome = stop.evaluate(repo.path, Policy())
            self.assertFalse(outcome.holds)
            self.assertEqual(stop.decision(outcome, advisory=False), {})

    def test_the_prescription_travels_with_the_block(self):
        with _Repository() as repo:
            repo.weaken()
            outcome = stop.evaluate(repo.path, Policy())
            reason = stop.decision(outcome, advisory=False)["reason"]
            self.assertIn("inv.currency", reason)
            self.assertIn("assertion_monotonicity", reason)
            self.assertIn("Restore", reason)


class TestItCannotTrapTheAgent(unittest.TestCase):
    """A gate on Stop that blocks its own retry is worse than no gate at all."""

    def setUp(self):
        self.repo = _Repository().__enter__()
        self.repo.weaken()
        self.outcome = stop.evaluate(self.repo.path, Policy())
        self.assertTrue(self.outcome.holds, "fixture must produce a finding")

    def tearDown(self):
        self.repo.__exit__(None, None, None)

    def test_the_second_pass_never_blocks(self):
        response = stop.decision(self.outcome, advisory=False, looped=True)
        self.assertNotIn("decision", response)
        self.assertIn("systemMessage", response)

    def test_and_says_why_it_is_letting_go(self):
        response = stop.decision(self.outcome, advisory=False, looped=True)
        self.assertIn("already resumed once", response["systemMessage"])

    def test_advisory_mode_reports_without_blocking(self):
        response = stop.decision(self.outcome, advisory=True)
        self.assertNotIn("decision", response)
        self.assertIn("systemMessage", response)

    def test_enforcing_mode_blocks(self):
        self.assertEqual(
            stop.decision(self.outcome, advisory=False)["decision"], "block"
        )


class TestBothSpellingsOfTheLoopFlag(unittest.TestCase):
    """The payload key has been written in each; guessing wrong strands an agent."""

    def test_snake_case(self):
        self.assertTrue(stop.suppressed({"stop_hook_active": True}))

    def test_camel_case(self):
        self.assertTrue(stop.suppressed({"stopHookActive": True}))

    def test_absent_means_first_pass(self):
        self.assertFalse(stop.suppressed({}))

    def test_false_means_first_pass(self):
        self.assertFalse(stop.suppressed({"stop_hook_active": False}))


class TestItFailsOpen(unittest.TestCase):
    """Uncertainty resolves toward letting the agent finish, always."""

    def test_outside_a_repository_nothing_is_held(self):
        with tempfile.TemporaryDirectory() as tmp:
            outcome = stop.evaluate(tmp, Policy())
            from yieldpoint.core import parsecache
            parsecache.close()
            self.assertFalse(outcome.holds)
            self.assertFalse(outcome.ran)
            self.assertTrue(outcome.reason)

    def test_a_verifier_crash_is_a_reason_not_an_exception(self):
        from unittest import mock

        with _Repository() as repo, mock.patch(
            "yieldpoint.verify.verify_diff", side_effect=RuntimeError("boom")
        ):
            repo.weaken()
            outcome = stop.evaluate(repo.path, Policy())
            self.assertFalse(outcome.holds)
            self.assertIn("boom", outcome.reason)


class TestTheCommand(unittest.TestCase):
    """End to end, the way Claude Code will actually invoke it."""

    def _run(self, payload, repo, *flags):
        return subprocess.run(
            [sys.executable, "-m", "yieldpoint", "hook", "--stop",
             "--root", str(repo), *flags],
            input=json.dumps(payload), capture_output=True, text=True,
            timeout=180, cwd=str(ROOT),
        )

    def test_a_shell_written_weakening_blocks_the_stop(self):
        with _Repository() as repo:
            repo.weaken()
            done = self._run({"stop_hook_active": False}, repo.path)
            self.assertEqual(json.loads(done.stdout)["decision"], "block")

    def test_it_always_exits_zero(self):
        """A non-zero exit reads as the hook being broken, not as a finding."""
        with _Repository() as repo:
            repo.weaken()
            self.assertEqual(self._run({}, repo.path).returncode, 0)

    def test_stdout_is_json_or_empty_and_never_both_kinds(self):
        with _Repository() as repo:
            repo.weaken()
            done = self._run({}, repo.path)
            json.loads(done.stdout)  # the whole of stdout, not a prefix
            self.assertNotIn("Yieldpoint", done.stdout.split('"reason"')[0])

    def test_a_clean_tree_writes_nothing_to_stdout(self):
        with _Repository() as repo:
            self.assertEqual(self._run({}, repo.path).stdout.strip(), "")
