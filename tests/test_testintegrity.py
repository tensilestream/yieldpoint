"""Test-contract rules are differential: pre-existing offences are not this change's."""

import unittest

from yieldpoint.core.assertions import extract
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
