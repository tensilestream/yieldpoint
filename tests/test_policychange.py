"""Loosening the rules is a change like any other.

Making the policy legible — so a person can audit it and an agent can tune it —
also hands an agent the cheapest route past any finding: raise the limit until
it goes away. These tests pin that route shut without closing the legitimate
one, which is a project deciding its own standards.
"""

import json
import unittest

from yieldpoint.core.policy import Policy, Structure
from yieldpoint.core.policychange import POLICY_WEAKENED, check
from yieldpoint.hook import blocks
from yieldpoint.verify import verify_change

BASE = {
    "structure": {"max_lines": 50, "exclude": ["vendor/**"]},
    "test_contract": {"assertion_monotonicity": "block"},
    "metrics": {"enabled": True},
}


def _check(**changes):
    after = {**BASE, **changes}
    return check(json.dumps(BASE), json.dumps(after), ".yieldpoint.json")[0]


class TestLoosening(unittest.TestCase):
    def test_raising_a_limit_names_both_values(self):
        found = _check(structure={"max_lines": 200})
        self.assertEqual([f.rule for f in found], [POLICY_WEAKENED])
        self.assertIn("50", found[0].detail)
        self.assertIn("200", found[0].detail)

    def test_switching_a_limit_off_is_not_a_missing_value(self):
        """``null`` reads as absence; it is the largest limit there is."""
        found = _check(structure={"max_lines": None})
        self.assertIn("no limit", found[0].detail)

    def test_lowering_a_severity_is_reported(self):
        found = _check(test_contract={"assertion_monotonicity": "repair"})
        self.assertIn("lowered from block to repair", found[0].detail)

    def test_switching_a_rule_off_is_reported_as_off(self):
        found = _check(test_contract={"assertion_monotonicity": None})
        self.assertIn("to off", found[0].detail)

    def test_excluding_more_paths_is_reported(self):
        found = _check(structure={"max_lines": 50, "exclude": ["vendor/**", "src/**"]})
        self.assertIn("src/**", found[0].detail)

    def test_disabling_the_ledger_is_reported_as_evidence_removed(self):
        found = _check(metrics={"enabled": False})
        self.assertIn("nothing records what ran", found[0].detail)

    def test_every_loosening_in_one_edit_gets_its_own_finding(self):
        found = _check(structure={"max_lines": 200, "exclude": ["vendor/**", "src/**"]},
                       metrics={"enabled": False})
        self.assertEqual(len(found), 3)


class TestTighteningIsSilent(unittest.TestCase):
    def test_lowering_a_limit_needs_no_defence(self):
        self.assertEqual(_check(structure={"max_lines": 20}), [])

    def test_raising_a_severity_needs_no_defence(self):
        self.assertEqual(
            _check(test_contract={"assertion_monotonicity": "block"},
                   structure={"max_lines": 50, "exclude": ["vendor/**"]}), [])

    def test_an_unchanged_policy_reports_nothing(self):
        self.assertEqual(_check(), [])


class TestScope(unittest.TestCase):
    def test_an_ordinary_json_file_is_not_a_policy(self):
        self.assertEqual(
            check('{"structure": {"max_lines": 50}}',
                  '{"structure": {"max_lines": 900}}', "package.json")[0], [])

    def test_a_policy_added_whole_has_nothing_to_weaken(self):
        self.assertEqual(check(None, json.dumps(BASE), ".yieldpoint.json")[0], [])

    def test_unparseable_json_is_skipped_rather_than_passed(self):
        """RULES.md section 5: a check that could not run reports no result."""
        findings, skipped = check(json.dumps(BASE), "{not json", ".yieldpoint.json")
        self.assertEqual(findings, [])
        self.assertEqual(len(skipped), 1)


class TestItNeverBlocks(unittest.TestCase):
    def setUp(self):
        self.verdict = verify_change(
            json.dumps(BASE),
            json.dumps({**BASE, "structure": {"max_lines": 500}}),
            ".yieldpoint.json")

    def test_the_loosening_is_reported(self):
        self.assertEqual([f.rule for f in self.verdict.findings], [POLICY_WEAKENED])

    def test_it_does_not_deny_the_edit(self):
        self.assertIs(blocks(self.verdict, Policy()), False)

    def test_it_does_not_deny_the_edit_even_when_structure_gates(self):
        """Otherwise a project could not relax a rule without first defeating it."""
        gated = Policy(structure=Structure(gates=True))
        self.assertIs(blocks(self.verdict, gated), False)


if __name__ == "__main__":
    unittest.main()
