"""Routing and gating: the decisions an agent loop makes without a model call.

The properties worth pinning are not the individual answers — those will be
tuned — but the guarantees a harness relies on to trust them at all:
determinism, no model call, admitting ignorance, and the ordering of the scale.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from yieldpoint.harness import (
    RISK_LEVELS, TIERS, Change, Gate, Score, measure, middleware, risk, tier,
)
from yieldpoint.harness.decisions import UNKNOWN, unknown

PROTECTED = {"protected_tests": ["**/test_*.py"]}

PLAIN = "import os\n\ndef f(a):\n    \"\"\"old\"\"\"\n    return a\n"
DOCSTRING_ONLY = "import os\n\ndef f(a):\n    \"\"\"new\"\"\"\n    return a\n"
STRUCTURAL = (
    "import json\nimport os\n\ndef f(a):\n    return a\n\n"
    "def g(b):\n    if b:\n        return 1\n    return 2\n"
)


class TestSignals(unittest.TestCase):
    def test_a_docstring_edit_is_not_structural(self):
        found = measure(Change("src/x.py", PLAIN, DOCSTRING_ONLY))
        self.assertFalse(found.structural)
        self.assertEqual(found.new_dependencies, ())

    def test_a_new_definition_and_import_are_structural(self):
        found = measure(Change("src/x.py", PLAIN, STRUCTURAL))
        self.assertTrue(found.structural)
        self.assertEqual(found.new_dependencies, ("json",))

    def test_an_unparseable_result_is_recorded_not_guessed(self):
        found = measure(Change("src/x.py", PLAIN, "def f(:\n"))
        self.assertIs(found.parses, False)
        self.assertIsNone(found.max_complexity)

    def test_a_language_with_no_analyser_says_so(self):
        found = measure(Change("src/x.ts", "const a = 1;", "const a = 2;"))
        self.assertFalse(found.analysable)
        self.assertIsNone(found.parses)


class TestRiskScale(unittest.TestCase):
    def test_the_scale_is_ordered(self):
        score = risk(Change("src/x.py", PLAIN, STRUCTURAL))
        self.assertEqual(score.levels, RISK_LEVELS)
        self.assertTrue(score.at_least("trivial"))
        self.assertFalse(score.at_least("critical"))

    def test_a_protected_test_is_the_top_of_the_scale(self):
        score = risk(Change("tests/test_x.py", PLAIN, DOCSTRING_ONLY), PROTECTED)
        self.assertEqual(score.value, "critical")
        self.assertTrue(score.at_least("high"))

    def test_every_level_used_is_in_the_scale(self):
        for change in (
            Change("src/x.py", PLAIN, DOCSTRING_ONLY),
            Change("src/x.py", PLAIN, STRUCTURAL),
            Change("src/x.py", PLAIN, "def f(:\n"),
            Change("src/x.ts", "a", "b"),
            Change("tests/test_x.py", PLAIN, DOCSTRING_ONLY),
        ):
            with self.subTest(change.path):
                self.assertIn(risk(change, PROTECTED).value, RISK_LEVELS)


class TestTier(unittest.TestCase):
    def test_cosmetic_work_gets_the_cheapest_model(self):
        self.assertEqual(tier(Change("src/x.py", PLAIN, DOCSTRING_ONLY)).value, "small")

    def test_a_protected_test_goes_to_a_person(self):
        decision = tier(Change("tests/test_x.py", PLAIN, DOCSTRING_ONLY), PROTECTED)
        self.assertEqual(decision.value, "human")

    def test_verified_mechanical_work_needs_no_model_at_all(self):
        decision = tier(Change("src/x.py", PLAIN, DOCSTRING_ONLY), verified=True)
        self.assertEqual(decision.value, "none")

    def test_every_tier_is_in_the_declared_set(self):
        for change, verified in (
            (Change("src/x.py", PLAIN, DOCSTRING_ONLY), None),
            (Change("src/x.py", PLAIN, DOCSTRING_ONLY), True),
            (Change("src/x.py", PLAIN, STRUCTURAL), None),
            (Change("tests/test_x.py", PLAIN, PLAIN), None),
        ):
            with self.subTest(change.path, verified=verified):
                self.assertIn(tier(change, PROTECTED, verified=verified).value, TIERS)

    def test_a_decision_carries_its_evidence(self):
        """A harness must be able to log why it routed, without asking anything."""
        decision = tier(Change("src/x.py", PLAIN, STRUCTURAL))
        self.assertTrue(decision.reason)
        self.assertIn("churn", decision.signals)
        self.assertIn("risk", decision.signals)


class TestDeterminism(unittest.TestCase):
    """The whole argument for computing these rather than asking."""

    def test_the_same_change_decides_the_same_way(self):
        change = Change("src/x.py", PLAIN, STRUCTURAL)
        first = [tier(change).to_dict() for _ in range(5)]
        self.assertEqual(first[1:], first[:-1])

    def test_risk_and_tier_agree_about_the_signals(self):
        change = Change("src/x.py", PLAIN, STRUCTURAL)
        self.assertEqual(risk(change).signals["churn"], tier(change).signals["churn"])


class TestUnknown(unittest.TestCase):
    def test_it_is_not_a_value_that_looks_like_an_answer(self):
        decision = unknown("tier", "no analyser")
        self.assertFalse(decision.known)
        self.assertEqual(decision.value, UNKNOWN)


class TestGate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.previous = Path.cwd()
        os.chdir(self.tmp.name)
        self.test = Path(self.tmp.name) / "test_invoice.py"
        self.test.write_text(
            "from billing import invoice\n\ndef test_total():\n"
            "    assert invoice.total == 42\n"
        )
        self.mw = middleware(policy=PROTECTED)

    def tearDown(self):
        os.chdir(self.previous)
        self.tmp.cleanup()

    def _edit(self, new: str) -> Gate:
        return self.mw.before_tool("Edit", {
            "file_path": str(self.test),
            "old_string": "assert invoice.total == 42",
            "new_string": new,
        })

    def test_a_weakening_edit_is_denied_before_it_runs(self):
        gate = self._edit("assert invoice.total")
        self.assertFalse(gate.allowed)
        self.assertIn("weakened", gate.reason)
        self.assertIn("Restore", gate.prescription)

    def test_a_legitimate_edit_is_allowed(self):
        self.assertTrue(self._edit("assert invoice.total == 99").allowed)

    def test_a_non_editing_tool_says_why_it_was_not_examined(self):
        gate = self.mw.before_tool("Read", {"file_path": "x"})
        self.assertTrue(gate.allowed)
        self.assertIn("not examined", gate.reason)

    def test_an_unreconstructable_payload_allows(self):
        """Fail open: a confused gate must not stand between anyone and work."""
        self.assertTrue(self.mw.before_tool("Edit", {"nonsense": True}).allowed)

    def test_assess_answers_everything_from_one_parse(self):
        result = self.mw.assess(Change("src/x.py", PLAIN, STRUCTURAL))
        self.assertEqual(
            result["risk"]["signals"]["churn"], result["tier"]["signals"]["churn"]
        )


if __name__ == "__main__":
    unittest.main()


class TestPolicyDrivenRouting(unittest.TestCase):
    """Thresholds are configuration, not constants.

    A team that cannot move a number without forking stops using the routing
    instead, which costs them the whole benefit to avoid one disagreement.
    """

    def test_a_threshold_can_be_raised(self):
        change = Change("src/x.py", PLAIN, PLAIN + "\n".join(
            f"# note {i}" for i in range(20)))
        self.assertEqual(risk(change).value, "low")
        self.assertEqual(risk(change, {"routing": {"small_churn": 40}}).value, "trivial")

    def test_escalate_paths_override_shape(self):
        """The escape hatch for importance the syntax tree cannot see."""
        change = Change("src/payments/rate.py", PLAIN, DOCSTRING_ONLY)
        self.assertEqual(risk(change).value, "trivial")
        escalated = {"routing": {"escalate_paths": ["src/payments/**"]}}
        self.assertEqual(risk(change, escalated).value, "critical")
        self.assertEqual(tier(change, escalated).value, "human")

    def test_contradictory_thresholds_are_rejected_not_applied(self):
        from yieldpoint.core.policy import Policy

        policy = Policy.load({"routing": {"small_churn": 100, "moderate_churn": 5}})
        self.assertEqual(policy.routing.small_churn, 12, "defaults must stand")
        self.assertTrue(any("must increase" in w for w in policy.warnings))

    def test_tiers_can_be_named_once_in_the_policy(self):
        mw = middleware({"routing": {"tiers": {"small": "haiku", "standard": "sonnet"}}})
        self.assertEqual(mw.model_name(Change("src/x.py", PLAIN, DOCSTRING_ONLY)), "haiku")


class TestFailurePolicy(unittest.TestCase):
    def test_it_fails_open_by_default(self):
        gate = middleware().before_tool("Edit", {"nonsense": True})
        self.assertTrue(gate.allowed)
        self.assertIn("fail_closed=False", gate.reason)

    def test_fail_closed_refuses_and_says_why(self):
        gate = middleware(fail_closed=True).before_tool("Edit", {"nonsense": True})
        self.assertFalse(gate.allowed)
        self.assertIn("could not verify", gate.prescription)


class TestDecisionSchema(unittest.TestCase):
    def test_every_decision_carries_a_version_and_a_certainty(self):
        from yieldpoint.harness.decisions import DECISION_SCHEMA_VERSION

        payload = tier(Change("src/x.py", PLAIN, DOCSTRING_ONLY)).to_dict()
        self.assertEqual(payload["schema_version"], DECISION_SCHEMA_VERSION)
        self.assertTrue(payload["certain"])

    def test_the_decision_version_is_pinned(self):
        """Bumping it is a deliberate act with consumers to update."""
        from yieldpoint.harness.decisions import DECISION_SCHEMA_VERSION

        self.assertEqual(DECISION_SCHEMA_VERSION, 1)
