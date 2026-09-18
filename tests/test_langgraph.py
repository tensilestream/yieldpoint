"""Stage 7 gate: the adapter needs no LangGraph installed, and the loop terminates.

A node is a callable and a conditional edge is a callable, so every behaviour
here is testable without the framework. `examples/langgraph_repair_loop.py`
exercises the same code inside a real compiled graph.
"""

import unittest

from aegisflow.core.policy import Policy
from aegisflow.core.verdict import Status, Verdict
from aegisflow.langgraph import (
    ATTEMPTS_KEY,
    BLOCK,
    ESCALATE,
    HISTORY_KEY,
    PASS,
    REPAIR,
    TRIPPED_KEY,
    make_router,
    observe,
    read_change,
    repair_context,
    route_on_verdict,
    signature,
    verdict_from,
    verify_node,
)

ORIGINAL = "def test_total():\n    assert inv.total == 42\n"
WEAKER = "def test_total():\n    assert inv.total is not None\n"


def change_state(after=WEAKER, before=ORIGINAL, path="tests/test_x.py"):
    return {"changes": [{"path": path, "before": before, "after": after}]}


class TestNode(unittest.TestCase):
    def setUp(self):
        self.node = verify_node(policy=Policy())

    def test_weakening_produces_a_repair_verdict(self):
        update = self.node(change_state())
        self.assertEqual(update["verdict"]["status"], REPAIR)
        self.assertIn("inv.total", update["prescription"])

    def test_clean_change_passes(self):
        self.assertEqual(self.node(change_state(after=ORIGINAL))["verdict"]["status"], PASS)

    def test_state_is_serialisable_for_checkpointers(self):
        import json

        json.dumps(self.node(change_state()))

    def test_attempts_increment_across_iterations(self):
        state = dict(change_state())
        for expected in (1, 2, 3):
            state.update(self.node(state))
            self.assertEqual(state[ATTEMPTS_KEY], expected)

    def test_missing_change_is_skipped_not_passed(self):
        update = self.node({})
        self.assertEqual(update["verdict"]["skipped"], ["no change found in state"])

    def test_change_without_a_path_is_skipped(self):
        update = self.node({"changes": [{"after": WEAKER}]})
        self.assertTrue(update["verdict"]["skipped"])

    def test_diff_input_is_accepted(self):
        diff = (
            "--- a/tests/test_x.py\n+++ b/tests/test_x.py\n"
            "@@ -1,2 +1,2 @@\n def test_total():\n"
            "-    assert inv.total == 42\n+    assert inv.total is not None\n"
        )
        update = self.node({"diff": diff, "root": "/nonexistent"})
        self.assertTrue(update["verdict"]["skipped"])

    def test_custom_extractor_overrides_the_convention(self):
        node = verify_node(policy=Policy(), extract=lambda s: {"changes": [s["mine"]]})
        update = node({"mine": {"path": "tests/t.py", "before": ORIGINAL, "after": WEAKER}})
        self.assertEqual(update["verdict"]["status"], REPAIR)

    def test_verdict_key_is_configurable(self):
        node = verify_node(policy=Policy(), verdict_key="aegis")
        self.assertIn("aegis", node(change_state()))


class TestReadChange(unittest.TestCase):
    def test_prefers_diff_then_changes(self):
        self.assertIn("diff", read_change({"diff": "d", "changes": [{}]}))
        self.assertIn("changes", read_change({"changes": [{"path": "a"}]}))

    def test_returns_none_when_absent(self):
        self.assertIsNone(read_change({"unrelated": 1}))

    def test_empty_collections_are_not_a_change(self):
        self.assertIsNone(read_change({"diff": "", "changes": []}))


class TestRouter(unittest.TestCase):
    def test_routes_on_verdict_status(self):
        for status, expected in (
            (Status.PASS, PASS), (Status.REPAIR, REPAIR),
            (Status.ESCALATE, ESCALATE), (Status.BLOCK, BLOCK),
        ):
            state = {"verdict": _verdict(status).to_dict()}
            self.assertEqual(route_on_verdict(state), expected, status)

    def test_repair_budget_escalates_when_exhausted(self):
        state = {"verdict": _verdict(Status.REPAIR).to_dict(), ATTEMPTS_KEY: 3}
        self.assertEqual(make_router(max_repairs=3)(state), ESCALATE)

    def test_repair_continues_while_budget_remains(self):
        state = {"verdict": _verdict(Status.REPAIR).to_dict(), ATTEMPTS_KEY: 1}
        self.assertEqual(make_router(max_repairs=3)(state), REPAIR)

    def test_stalled_loop_escalates_before_the_budget_runs_out(self):
        state = {"verdict": _verdict(Status.REPAIR).to_dict(), ATTEMPTS_KEY: 1, TRIPPED_KEY: True}
        self.assertEqual(make_router(max_repairs=99)(state), ESCALATE)

    def test_missing_verdict_routes_to_pass(self):
        self.assertEqual(route_on_verdict({}), PASS)

    def test_escalation_targets_are_configurable(self):
        state = {"verdict": _verdict(Status.REPAIR).to_dict(), ATTEMPTS_KEY: 9}
        self.assertEqual(make_router(max_repairs=1, on_exhausted="giveup")(state), "giveup")


class TestLoopBreaker(unittest.TestCase):
    def test_identical_attempts_trip_the_breaker(self):
        history, tripped = [], False
        for _ in range(3):
            history, tripped = observe(history, "same", max_repeats=3)
        self.assertTrue(tripped)

    def test_differing_attempts_do_not_trip(self):
        history, tripped = [], False
        for i in range(5):
            history, tripped = observe(history, f"attempt-{i}", max_repeats=3)
        self.assertFalse(tripped)

    def test_history_is_bounded_by_the_window(self):
        history = []
        for i in range(20):
            history, _ = observe(history, f"a{i}", window=6)
        self.assertEqual(len(history), 6)

    def test_signature_is_stable_and_order_sensitive(self):
        self.assertEqual(signature("a", "b"), signature("a", "b"))
        self.assertNotEqual(signature("a", "b"), signature("b", "a"))

    def test_signature_separates_fields(self):
        """Concatenation must not let 'ab'+'c' collide with 'a'+'bc'."""
        self.assertNotEqual(signature("ab", "c"), signature("a", "bc"))

    def test_node_trips_on_a_repeated_proposal(self):
        node = verify_node(policy=Policy(), max_repeats=2)
        state = dict(change_state())
        state.update(node(state))
        self.assertFalse(state[TRIPPED_KEY])
        state.update(node(state))
        self.assertTrue(state[TRIPPED_KEY])

    def test_node_does_not_trip_when_the_proposal_changes(self):
        node = verify_node(policy=Policy(), max_repeats=2)
        state = dict(change_state())
        state.update(node(state))
        state.update({**change_state(after="def test_total():\n    assert True\n"),
                      HISTORY_KEY: state[HISTORY_KEY]})
        state.update(node(state))
        self.assertFalse(state[TRIPPED_KEY])


class TestRepairContext(unittest.TestCase):
    def test_feedback_names_the_subject_and_the_attempt(self):
        state = dict(change_state())
        state.update(verify_node(policy=Policy())(state))
        text = repair_context(state)
        self.assertIn("inv.total", text)
        self.assertIn("attempt 1", text)

    def test_no_findings_means_no_feedback(self):
        self.assertEqual(repair_context({"verdict": _verdict(Status.PASS).to_dict()}), "")


class TestVerdictFrom(unittest.TestCase):
    def test_rehydrates_a_serialised_verdict(self):
        verdict = _verdict(Status.REPAIR)
        self.assertEqual(verdict_from({"verdict": verdict.to_dict()}).status, Status.REPAIR)

    def test_accepts_a_verdict_object(self):
        self.assertIs(verdict_from({"verdict": Verdict.of([])}).status, Status.PASS)

    def test_missing_verdict_is_a_pass(self):
        self.assertIs(verdict_from({}).status, Status.PASS)


def _verdict(status: Status) -> Verdict:
    if status is Status.PASS:
        return Verdict.of([])
    from aegisflow.core.verdict import Finding

    return Verdict.of([Finding(
        rule="assertion_monotonicity", status=status, file="tests/t.py", line=1,
        detail="weakened", prescription="restore it",
    )])


if __name__ == "__main__":
    unittest.main()
