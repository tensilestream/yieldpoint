"""What is allowed to stop a commit.

"This function is long" and "this assertion no longer holds" are not the same
claim. Giving them the same power over a commit is how a gate gets passed
``--no-verify`` out of habit, and the habit does not distinguish between them —
so the rule that mattered is muted along with the one that did not.

Maintainability findings are therefore reported and counted but do not fail a
run, unless ``structure.gates`` says otherwise. These tests fix that in place in
both directions: a weakening must still stop, and turning the switch on must
still work.
"""

from __future__ import annotations

import unittest

from yieldpoint.commands import _exit_for, only_maintainability
from yieldpoint.core.policy import Policy, Structure
from yieldpoint.core.structure import CHANGE_TOO_LARGE, FUNCTION_TOO_LONG
from yieldpoint.core.verdict import Confidence, Finding, Status, Verdict
from yieldpoint.hook import blocks

EXIT_OK, EXIT_FINDINGS = 0, 1


def _finding(rule: str) -> Finding:
    return Finding(rule=rule, status=Status.REPAIR, file="a.py", line=1,
                   detail="d", prescription="p", confidence=Confidence.EXACT)


def _verdict(*rules: str) -> Verdict:
    return Verdict.of([_finding(r) for r in rules], checked=["a.py"])


class TestShapeDoesNotStopACommit(unittest.TestCase):
    def test_a_long_function_alone_exits_zero(self):
        verdict = _verdict(FUNCTION_TOO_LONG)
        self.assertEqual(_exit_for(verdict, Policy()), EXIT_OK)

    def test_an_oversized_change_alone_exits_zero(self):
        """The case that blocked a documentation commit."""
        self.assertEqual(_exit_for(_verdict(CHANGE_TOO_LARGE), Policy()), EXIT_OK)

    def test_the_verdict_still_says_repair(self):
        """Not blocking is not the same as not reported."""
        verdict = _verdict(CHANGE_TOO_LARGE)
        self.assertIs(verdict.status, Status.REPAIR)
        self.assertEqual(len(verdict.findings), 1)

    def test_the_editor_hook_does_not_deny_the_edit(self):
        self.assertFalse(blocks(_verdict(FUNCTION_TOO_LONG), Policy()))


class TestAWeakeningStillStops(unittest.TestCase):
    def test_a_weakened_assertion_exits_one(self):
        self.assertEqual(
            _exit_for(_verdict("assertion_monotonicity"), Policy()), EXIT_FINDINGS)

    def test_one_weakening_among_shape_findings_still_stops(self):
        """The mixed case. A real finding must not be diluted by company."""
        verdict = _verdict(FUNCTION_TOO_LONG, "assertion_monotonicity", CHANGE_TOO_LARGE)
        self.assertFalse(only_maintainability(verdict, Policy()))
        self.assertEqual(_exit_for(verdict, Policy()), EXIT_FINDINGS)

    def test_the_editor_hook_still_denies_it(self):
        self.assertTrue(blocks(_verdict("assertion_monotonicity"), Policy()))

    def test_a_removed_export_is_not_maintainability(self):
        """Refactor rules describe what moved, not what shape it is."""
        self.assertFalse(only_maintainability(_verdict("export_removed"), Policy()))


class TestTheSwitchWorks(unittest.TestCase):
    def test_gates_true_makes_shape_binding_again(self):
        strict = Policy(structure=Structure(gates=True))
        self.assertFalse(only_maintainability(_verdict(CHANGE_TOO_LARGE), strict))
        self.assertEqual(_exit_for(_verdict(CHANGE_TOO_LARGE), strict), EXIT_FINDINGS)
        self.assertTrue(blocks(_verdict(CHANGE_TOO_LARGE), strict))

    def test_it_is_off_by_default(self):
        self.assertFalse(Policy().structure.gates)

    def test_it_is_read_from_the_config_file(self):
        import json
        import tempfile
        from pathlib import Path

        path = Path(tempfile.mkdtemp()) / ".yieldpoint.json"
        path.write_text(json.dumps({"structure": {"gates": True}}))
        self.assertTrue(Policy.load(str(path)).structure.gates)


class TestNothingElseChanged(unittest.TestCase):
    def test_a_clean_verdict_still_passes(self):
        self.assertEqual(_exit_for(Verdict.of([], checked=["a.py"]), Policy()), EXIT_OK)

    def test_unverified_is_still_not_a_pass(self):
        verdict = Verdict.of([], checked=[], skipped=["a.ts: no analyser"])
        self.assertIs(verdict.status, Status.UNVERIFIED)
        self.assertEqual(_exit_for(verdict, Policy()), 3)

    def test_without_a_policy_the_old_behaviour_holds(self):
        """Callers that pass no policy must not silently lose their gate."""
        self.assertEqual(_exit_for(_verdict(CHANGE_TOO_LARGE)), EXIT_FINDINGS)


if __name__ == "__main__":
    unittest.main()
