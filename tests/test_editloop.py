"""The per-edit gate must not be able to deny the same thing forever.

A capable agent escapes a repeated denial by batching its edits through a
shell, where this gate sees nothing at all. A weaker one cannot, and simply
stops making progress. These tests fix the bound so neither depends on how
clever the agent is.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from yieldpoint import editloop
from yieldpoint.commands import hook_command
from yieldpoint.core.policy import Policy

ORIGINAL = "def test_total():\n    assert inv.total == 42\n"
WEAKER = "def test_total():\n    assert inv.total is not None\n"


def _payload(path: str, after: str, session: str = "s1") -> str:
    return json.dumps({
        "session_id": session, "tool_name": "Write",
        "tool_input": {"file_path": path, "content": after},
    })


class TestTheBudget(unittest.TestCase):
    def test_the_same_denial_counts_up(self):
        with tempfile.TemporaryDirectory() as directory:
            key = editloop.key_for("s1", "a.py", ["dangling_reference"])
            self.assertEqual(editloop.record(key, root=directory), 1)
            self.assertEqual(editloop.record(key, root=directory), 2)
            self.assertEqual(editloop.attempts(key, root=directory), 2)

    def test_a_different_finding_starts_again(self):
        """Being told something new is progress, and earns a fresh budget."""
        with tempfile.TemporaryDirectory() as directory:
            first = editloop.key_for("s1", "a.py", ["dangling_reference"])
            second = editloop.key_for("s1", "a.py", ["weak_new_test"])
            editloop.record(first, root=directory)
            editloop.record(first, root=directory)
            self.assertEqual(editloop.record(second, root=directory), 1)

    def test_an_allowed_edit_to_that_file_ends_the_run(self):
        with tempfile.TemporaryDirectory() as directory:
            key = editloop.key_for("s1", "a.py", ["dangling_reference"])
            editloop.record(key, root=directory)
            editloop.progressed("a.py", root=directory)
            self.assertEqual(editloop.attempts(key, root=directory), 0)

    def test_an_allowed_edit_elsewhere_does_not(self):
        """Otherwise one unrelated edit buys an unbounded budget on the file
        the agent is actually stuck on."""
        with tempfile.TemporaryDirectory() as directory:
            key = editloop.key_for("s1", "a.py", ["dangling_reference"])
            editloop.record(key, root=directory)
            editloop.progressed("other.py", root=directory)
            self.assertEqual(editloop.attempts(key, root=directory), 1)

    def test_the_budget_comes_from_policy(self):
        self.assertEqual(editloop.budget(Policy()), 3)
        self.assertEqual(
            editloop.budget(Policy.load({"loop_breaker": {"max_repeats_without_progress": 5}})), 5)
        self.assertEqual(editloop.budget(None), 3)

    def test_release_happens_only_past_the_budget(self):
        policy = Policy()
        self.assertIs(editloop.released(editloop.budget(policy), policy), False)
        self.assertIs(editloop.released(editloop.budget(policy) + 1, policy), True)

    def test_the_notice_says_the_finding_still_stands(self):
        """Releasing is not forgiving, and the agent must not read it as a pass."""
        text = editloop.notice(4, ["dangling_reference"])
        self.assertIn("dangling_reference", text)
        self.assertIn("has not been waived", text)
        self.assertIn("yieldpoint review", text)


class TestTheGateStandsDown(unittest.TestCase):
    """End to end: the same weakening edit, offered over and over."""

    def _run(self, directory: str, path: Path) -> tuple[int, str]:
        errors = io.StringIO()
        args = Namespace(policy=None, root=directory, advisory=False,
                         json_decision=False, speak=False)
        with mock.patch("sys.stdin", io.StringIO(_payload(str(path), WEAKER))):
            with redirect_stderr(errors), redirect_stdout(io.StringIO()):
                code = hook_command(args)
        return code, errors.getvalue()

    def test_a_repeated_denial_is_released_and_says_why(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test_invoice.py"
            path.write_text(ORIGINAL)
            codes = [self._run(directory, path)[0] for _ in range(3)]
            self.assertEqual(codes, [2, 2, 2], "the first attempts must still deny")
            code, message = self._run(directory, path)
            self.assertEqual(code, 0)
            self.assertIn("has not been waived", message)

    def test_the_json_decision_path_releases_too(self):
        """A host reading structured output must not be the one that loops."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test_invoice.py"
            path.write_text(ORIGINAL)
            for _ in range(3):
                self._run(directory, path)
            output = io.StringIO()
            args = Namespace(policy=None, root=directory, advisory=False,
                             json_decision=True, speak=False)
            with mock.patch("sys.stdin", io.StringIO(_payload(str(path), WEAKER))):
                with redirect_stdout(output), redirect_stderr(io.StringIO()):
                    hook_command(args)
            decision = json.loads(output.getvalue())["hookSpecificOutput"]
            self.assertEqual(decision["permissionDecision"], "allow")
            self.assertIn("has not been waived", decision["permissionDecisionReason"])


if __name__ == "__main__":
    unittest.main()
