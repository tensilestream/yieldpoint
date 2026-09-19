"""Stage 5 gate: the hook denies a weakening edit, and fails open on everything else."""

import json
import os
import tempfile
import unittest
from pathlib import Path

from aegisflow.core.verdict import Confidence, Finding, Status, Verdict
from aegisflow.hook import (
    Change, blocks, build_change, decision_json, evaluate, read_payload, render,
)

ORIGINAL = (
    "from decimal import Decimal\n\n"
    'def test_total(inv):\n    assert inv.total == 42\n    assert inv.currency == "USD"\n'
)


class HookCase(unittest.TestCase):
    """Each test runs in a throwaway repo with AegisFlow's own default policy."""

    def setUp(self):
        self._previous = Path.cwd()
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        (root / "tests").mkdir()
        self.target = root / "tests" / "test_invoice.py"
        self.target.write_text(ORIGINAL, encoding="utf-8")
        os.chdir(root)

    def tearDown(self):
        os.chdir(self._previous)
        self._tmp.cleanup()

    def edit(self, old: str, new: str) -> dict:
        return {
            "tool_name": "Edit",
            "tool_input": {"file_path": str(self.target), "old_string": old, "new_string": new},
        }


class TestReconstruction(HookCase):
    def test_edit_is_applied_to_disk_content(self):
        change = build_change(self.edit("== 42", "is not None"))
        self.assertTrue(change.usable)
        self.assertEqual(change.before, ORIGINAL)
        self.assertIn("is not None", change.after)

    def test_write_replaces_whole_content(self):
        change = build_change(
            {"tool_name": "Write",
             "tool_input": {"file_path": str(self.target), "content": "def test_x():\n    pass\n"}}
        )
        self.assertEqual(change.before, ORIGINAL)
        self.assertEqual(change.after, "def test_x():\n    pass\n")

    def test_multiedit_applies_edits_in_order(self):
        change = build_change({
            "tool_name": "MultiEdit",
            "tool_input": {"file_path": str(self.target), "edits": [
                {"old_string": "== 42", "new_string": "== 43"},
                {"old_string": "== 43", "new_string": "is not None"},
            ]},
        })
        self.assertIn("is not None", change.after)

    def test_replace_all_replaces_every_occurrence(self):
        self.target.write_text("def test_x():\n    assert a == 1\n    assert a == 1\n")
        change = build_change({
            "tool_name": "Edit",
            "tool_input": {"file_path": str(self.target), "old_string": "assert a == 1",
                           "new_string": "assert a", "replace_all": True},
        })
        self.assertEqual(change.after.count("assert a\n"), 2)


class TestFailsOpen(HookCase):
    """Uncertainty must allow the edit. A confused verifier that blocks is worse than none."""

    def test_unknown_tool_is_not_a_change(self):
        self.assertFalse(build_change({"tool_name": "Bash", "tool_input": {"command": "ls"}}).usable)

    def test_missing_file_path(self):
        self.assertFalse(build_change({"tool_name": "Edit", "tool_input": {}}).usable)

    def test_unmatched_old_string(self):
        change = build_change(self.edit("text that is absent", "x"))
        self.assertFalse(change.usable)
        self.assertIn("not found", change.reason)

    def test_unreadable_file(self):
        payload = {"tool_name": "Edit", "tool_input": {
            "file_path": "/nonexistent/dir/test_x.py", "old_string": "a", "new_string": "b"}}
        self.assertFalse(build_change(payload).usable)

    def test_malformed_payload_yields_a_passing_verdict(self):
        verdict, change = evaluate(read_payload("not json at all"))
        self.assertIs(verdict.status, Status.PASS)
        self.assertFalse(change.usable)

    def test_empty_payload(self):
        self.assertEqual(read_payload(""), {})


class TestDecisions(HookCase):
    def test_weakening_edit_is_denied(self):
        verdict, _ = evaluate(self.edit("assert inv.total == 42", "assert inv.total is not None"))
        self.assertIsNot(verdict.status, Status.PASS)
        self.assertTrue(blocks(verdict))

    def test_strengthening_edit_is_allowed(self):
        verdict, _ = evaluate(self.edit("== 42", "== Decimal('42.00')"))
        self.assertIs(verdict.status, Status.PASS)
        self.assertFalse(blocks(verdict))

    def test_deleting_an_assertion_is_denied(self):
        verdict, _ = evaluate(self.edit("    assert inv.total == 42\n", ""))
        self.assertTrue(blocks(verdict))

    def test_tautology_write_is_denied(self):
        verdict, _ = evaluate({"tool_name": "Write", "tool_input": {
            "file_path": str(self.target), "content": "def test_total():\n    assert True\n"}})
        self.assertTrue(blocks(verdict))

    def test_non_test_file_is_allowed(self):
        source = Path("invoice.py")
        source.write_text("def total():\n    return 42\n")
        verdict, _ = evaluate({"tool_name": "Edit", "tool_input": {
            "file_path": str(source.resolve()), "old_string": "42", "new_string": "0"}})
        self.assertIs(verdict.status, Status.PASS)

    def test_repair_denies_because_a_hook_has_no_router(self):
        verdict, _ = evaluate(self.edit("== 42", "is not None"))
        self.assertIs(verdict.status, Status.REPAIR)
        self.assertTrue(blocks(verdict))


class TestMessage(HookCase):
    def test_message_names_rule_location_and_remedy(self):
        verdict, change = evaluate(self.edit("== 42", "is not None"))
        message = render(verdict, change)
        self.assertIn("assertion_monotonicity", message)
        self.assertIn("test_invoice.py", message)
        self.assertIn("inv.total", message)

    def test_message_discourages_editing_the_test_instead(self):
        verdict, change = evaluate(self.edit("== 42", "is not None"))
        self.assertIn("Fix the code under test", render(verdict, change))


if __name__ == "__main__":
    unittest.main()


class TestUnverifiedFailsOpen(unittest.TestCase):
    """A change nothing could analyse must not stand between a person and an edit.

    The hook has only allow and deny, so an honest "I checked nothing" has to
    resolve to allow. The graph is where that choice is configurable; see
    ``make_router(on_unverified=...)``.
    """

    def setUp(self):
        self.verdict = Verdict.of([], skipped=["a.ts: no exact analyser for this language yet"])

    def test_status_is_unverified_not_pass(self):
        self.assertIs(self.verdict.status, Status.UNVERIFIED)

    def test_it_does_not_block(self):
        self.assertFalse(blocks(self.verdict))

    def test_the_decision_payload_allows(self):
        payload = json.loads(decision_json(self.verdict, Change(path="a.ts")))
        self.assertEqual(
            payload["hookSpecificOutput"]["permissionDecision"], "allow"
        )


class TestBlockMessageHeadline(unittest.TestCase):
    """The first line must describe the findings that are actually present.

    A maintainability finding reported as "weakens what the test suite verifies"
    is a claim the reader can check and find false, which costs more credibility
    than the simpler wording saves.
    """

    @staticmethod
    def _verdict(rule):
        return Verdict.of([Finding(
            rule=rule, status=Status.REPAIR, file="a.py", line=1,
            detail="d", prescription="p", confidence=Confidence.EXACT,
        )], checked=["a.py"])

    def test_a_weakened_test_says_so(self):
        message = render(self._verdict("assertion_monotonicity"), Change(path="a.py"))
        self.assertIn("weakens what the test suite verifies", message)

    def test_a_structural_finding_does_not_claim_a_weakened_test(self):
        message = render(self._verdict("file_too_long"), Change(path="a.py"))
        self.assertNotIn("test suite", message)
        self.assertIn("breaks a rule this project enforces", message)

    def test_both_kinds_present_says_both(self):
        verdict = self._verdict("assertion_monotonicity").merge(
            self._verdict("file_too_long"))
        message = render(verdict, Change(path="a.py"))
        self.assertIn("weakens what the test suite verifies", message)
        self.assertIn("breaks a project rule", message)
