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
from yieldpoint.core.verdict import Status, Verdict

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


class TestShapeFindingsDoNotHoldTheDoor(unittest.TestCase):
    """This gate must block on the same things the per-edit gate blocks on.

    It did not: `hook.blocks` and `review`'s exit code both honour
    `structure.gates`, and this one ignored it. A change could be waved through
    on every single edit and then refused at the door — and `change_too_large`,
    whose only remedy is a commit the agent is usually not permitted to make,
    could hold a session open with nothing it could legally do to satisfy it.
    """

    def _shape(self, rule: str, policy=None):
        from yieldpoint.core.verdict import Finding

        outcome = stop.Outcome(
            Verdict.of([Finding(rule=rule, status=Status.REPAIR, file="a.py", line=1,
                                detail="d", prescription="p")]))
        outcome.policy = Policy() if policy is None else policy
        return outcome

    def test_a_shape_finding_reports_without_blocking(self):
        outcome = self._shape("change_too_large")
        self.assertFalse(outcome.holds)
        self.assertEqual(stop.decision(outcome, advisory=False), {})

    def test_a_weakening_still_blocks(self):
        outcome = self._shape("assertion_monotonicity")
        self.assertTrue(outcome.holds)
        self.assertEqual(stop.decision(outcome, advisory=False)["decision"], "block")

    def test_structure_gates_makes_shape_binding_again(self):
        from yieldpoint.core.verdict import Finding

        outcome = stop.Outcome(
            Verdict.of([Finding(rule="change_too_large", status=Status.REPAIR,
                                file="a.py", line=1, detail="d", prescription="p")]),
            )
        outcome.policy = Policy.load({"structure": {"gates": True}})
        self.assertIs(outcome.holds, True)
        self.assertEqual(stop.decision(outcome, advisory=False)["decision"], "block")

    def test_without_a_policy_it_still_holds(self):
        """Older callers passed no policy; they must not silently stop blocking."""
        outcome = self._shape("change_too_large")
        outcome.policy = None
        self.assertIs(outcome.holds, True)
        self.assertEqual(stop.decision(outcome, advisory=False)["decision"], "block")


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


class TestItOnlyOffersAWayOutThatExists(unittest.TestCase):
    """The hook blocked on `change_too_large` and told the reader to
    acknowledge it in the source. The finding's location is "24 files", line 0
    — there is no source line, so the advertised route did not exist.

    The other route it named, raising the limit in the config, is the one
    `policy_weakened` reports as loosening a rule under pressure. Between them
    the message offered a reader no action they could actually take.
    """

    def _finding(self, rule, file, line):
        from yieldpoint.core.verdict import Finding, Status

        return Finding(rule=rule, status=Status.REPAIR, file=file, line=line,
                       detail="d", prescription="p")

    def test_a_change_level_finding_has_no_line_to_acknowledge(self):
        self.assertIs(self._placeable_for("change_too_large", "24 files", 0), False)

    def _placeable_for(self, rule, file, line):
        from yieldpoint.stop import _placeable

        return _placeable(self._finding(rule, file, line))

    def test_a_finding_in_a_file_does(self):
        self.assertIs(self._placeable_for("file_too_long", "src/a.py", 1), True)

    def test_the_message_omits_the_route_when_nothing_can_take_it(self):
        from yieldpoint.stop import _ways_out

        text = _ways_out([self._finding("change_too_large", "24 files", 0)], ".")
        self.assertNotIn("yieldpoint: allow", text)
        self.assertIn("smaller pieces", text)

    def test_the_message_keeps_the_route_when_something_can(self):
        from yieldpoint.stop import _ways_out

        text = _ways_out([self._finding("change_too_large", "24 files", 0),
                          self._finding("file_too_long", "src/a.py", 1)], ".")
        self.assertIn("yieldpoint: allow", text)

    def test_it_always_names_somewhere_to_change_the_rule(self):
        from yieldpoint.stop import _ways_out

        for findings in ([self._finding("change_too_large", "24 files", 0)],
                         [self._finding("file_too_long", "src/a.py", 1)]):
            self.assertIn("yieldpoint", _ways_out(findings, "."))
