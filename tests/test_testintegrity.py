"""Test-contract rules are differential: pre-existing offences are not this change's."""

import unittest

from yieldpoint.core.assertions import extract
from yieldpoint.verify import verify_change
from yieldpoint.core.testintegrity import (
    DISABLED_ASSERTION,
    EMPTY_TEST,
    SKIP_MARKER,
    VACUOUS_ASSERTION,
    compare,
    inspect,
)

CLEAN = "def test_a():\n    assert x == 1\n"


def rules(before: str, after: str):
    return [o.rule for o in compare(extract(before), extract(after))]


class TestDetection(unittest.TestCase):
    def test_new_skip_marker(self):
        after = "@pytest.mark.skip\ndef test_a():\n    assert x == 1\n"
        self.assertEqual(rules(CLEAN, after), [SKIP_MARKER])

    def test_xfail_marker(self):
        after = "@pytest.mark.xfail\ndef test_a():\n    assert x == 1\n"
        self.assertEqual(rules(CLEAN, after), [SKIP_MARKER])

    def test_emptied_body(self):
        self.assertEqual(rules(CLEAN, "def test_a():\n    pass\n"), [EMPTY_TEST])

    def test_body_with_no_assertions_at_all(self):
        self.assertEqual(rules(CLEAN, "def test_a():\n    do_work()\n"), [EMPTY_TEST])

    def test_tautology(self):
        self.assertEqual(rules(CLEAN, "def test_a():\n    assert True\n"), [VACUOUS_ASSERTION])

    def test_tautology_does_not_also_report_empty(self):
        """The vacuous finding is specific; reporting 'asserts nothing' too is noise."""
        self.assertNotIn(EMPTY_TEST, rules(CLEAN, "def test_a():\n    assert True\n"))

    def test_swallowed_assertion(self):
        after = (
            "def test_a():\n    try:\n        assert x == 1\n"
            "    except Exception:\n        pass\n"
        )
        self.assertEqual(rules(CLEAN, after), [DISABLED_ASSERTION])


class TestDifferential(unittest.TestCase):
    def test_preexisting_offence_is_not_attributed_to_this_change(self):
        skipped = "@pytest.mark.skip\ndef test_a():\n    assert x == 1\n"
        self.assertEqual(compare(extract(skipped), extract(skipped)), ())

    def test_removing_an_offence_reports_nothing(self):
        skipped = "@pytest.mark.skip\ndef test_a():\n    assert x == 1\n"
        self.assertEqual(compare(extract(skipped), extract(CLEAN)), ())

    def test_everything_in_a_new_file_is_new(self):
        after = "@pytest.mark.skip\ndef test_a():\n    assert True\n"
        self.assertEqual(set(rules("", after)), {SKIP_MARKER, VACUOUS_ASSERTION})

    def test_offence_added_to_a_second_test_is_reported(self):
        before = CLEAN + "\ndef test_b():\n    assert y == 2\n"
        after = CLEAN + "\n@pytest.mark.skip\ndef test_b():\n    assert y == 2\n"
        self.assertEqual(rules(before, after), [SKIP_MARKER])


class TestInspection(unittest.TestCase):
    def test_clean_source_has_no_offences(self):
        self.assertEqual(inspect(extract(CLEAN)), ())

    def test_unparseable_source_yields_nothing(self):
        self.assertEqual(inspect(extract("def test_a(:")), ())

    def test_offence_carries_a_prescription(self):
        offences = compare(extract(CLEAN), extract("def test_a():\n    assert True\n"))
        self.assertTrue(offences[0].prescription)


if __name__ == "__main__":
    unittest.main()


class TestWeakNewTests(unittest.TestCase):
    """A test can arrive weak as well as be made weak.

    Monotonicity compares a before state with an after state, so it is blind to
    a test that never had a stronger version. That is exactly the shape an
    agent produces when asked to add a feature *with tests*.
    """

    POLICY = {"test_contract": {
        "protected_patterns": ["**/tests/**", "**/test_*.py"],
        "assertion_monotonicity": "block",
        "forbid_weak_new_tests": "repair",
    }}

    def _rules(self, before, after):
        """Contract rules only. An undefined name in a fixture makes
        `dangling_reference` fire, which is true but not what these test."""
        verdict = verify_change(before, after, "tests/test_billing.py", self.POLICY)
        return sorted({f.rule for f in verdict.findings
                       if f.rule != "dangling_reference"})

    def test_a_new_test_that_only_checks_non_null_is_reported(self):
        self.assertIn("weak_new_test",
                      self._rules(None, "def test_t():\n    assert total is not None\n"))

    def test_a_new_test_that_only_checks_truthiness_is_reported(self):
        self.assertIn("weak_new_test",
                      self._rules(None, "def test_t():\n    assert total\n"))

    def test_a_new_test_that_pins_a_value_is_silent(self):
        self.assertEqual(self._rules(None, "def test_t():\n    assert total == 42\n"), [])

    def test_one_weak_guard_beside_a_real_assertion_is_silent(self):
        """A not-null guard before the real check is ordinary style."""
        self.assertEqual(
            self._rules(None, "def test_t():\n    assert total is not None\n"
                              "    assert total == 42\n"), [])

    def test_a_pre_existing_weak_test_is_not_blamed_on_this_change(self):
        weak = "def test_t():\n    assert total is not None\n"
        self.assertEqual(self._rules(weak, weak + "\n\ndef helper():\n    return 1\n"), [])

    def test_a_weakened_test_is_reported_once_by_monotonicity(self):
        """Not twice. Monotonicity names the subject and the strength lost;
        adding a vaguer second finding buries the useful one."""
        self.assertEqual(
            self._rules("def test_t():\n    assert total == 42\n",
                        "def test_t():\n    assert total is not None\n"),
            ["assertion_monotonicity"])

    def test_a_raises_assertion_is_not_weak(self):
        self.assertEqual(
            self._rules(None, "import pytest\n\n\ndef test_t():\n"
                              "    with pytest.raises(ValueError):\n        total(-1)\n"),
            [])

    def test_a_membership_assertion_is_not_weak(self):
        self.assertEqual(
            self._rules(None, "def test_t():\n    assert total in (12, 13)\n"), [])

    def test_an_empty_test_is_left_to_its_own_rule(self):
        self.assertNotIn("weak_new_test",
                         self._rules(None, "def test_t():\n    pass\n"))
