"""Stage 1 gate: every supported assertion form reduces to the right triple."""

import unittest

from aegisflow.core.assertions import extract
from aegisflow.core.relation import Relation as R


def single(body: str):
    """Extract the one assertion from a one-test source snippet."""
    result = extract(f"def test_x():\n{body}\n")
    assertions = result.tests[0].assertions
    assert len(assertions) == 1, f"expected 1 assertion, got {len(assertions)}"
    return assertions[0]


class TestBareAsserts(unittest.TestCase):
    def test_equality(self):
        a = single("    assert invoice.total == 42")
        self.assertEqual((a.subject, a.relation, a.expected), ("invoice.total", R.EQ, "42"))

    def test_is_none_is_exact_but_is_not_none_is_weak(self):
        self.assertIs(single("    assert x is None").relation, R.EQ)
        self.assertIs(single("    assert x is not None").relation, R.NON_NULL)
        self.assertIs(single("    assert x != None").relation, R.NON_NULL)

    def test_comparison_and_membership(self):
        self.assertIs(single("    assert x > 5").relation, R.COMPARISON)
        self.assertIs(single("    assert x in xs").relation, R.MEMBERSHIP)

    def test_truthiness(self):
        self.assertIs(single("    assert x").relation, R.TRUTHY)
        self.assertIs(single("    assert not x").relation, R.TRUTHY)

    def test_tautology_is_vacuous(self):
        self.assertIs(single("    assert True").relation, R.VACUOUS)
        self.assertIs(single("    assert 1").relation, R.VACUOUS)

    def test_reversed_operands_are_normalised(self):
        a = single("    assert 42 == invoice.total")
        self.assertEqual(a.subject, "invoice.total")
        self.assertEqual(a.expected, "42")

    def test_conjunction_counts_as_two_assertions(self):
        tests = extract("def test_x():\n    assert a == 1 and b == 2\n").tests[0]
        self.assertEqual([x.subject for x in tests.assertions], ["a", "b"])


class TestFrameworkForms(unittest.TestCase):
    def test_unittest_methods(self):
        cases = {
            "self.assertEqual(a.b, 3)": R.EQ,
            "self.assertIsNone(a.b)": R.EQ,
            "self.assertIsNotNone(a.b)": R.NON_NULL,
            "self.assertTrue(a.b)": R.TRUTHY,
            "self.assertIn(a.b, xs)": R.MEMBERSHIP,
            "self.assertGreater(a.b, 3)": R.COMPARISON,
        }
        for source, expected in cases.items():
            self.assertIs(single(f"    {source}").relation, expected, source)

    def test_pytest_raises_context_manager(self):
        a = single("    with pytest.raises(ValueError):\n        boom()")
        self.assertIs(a.relation, R.RAISES)

    def test_helper_call_is_opaque_not_guessed(self):
        a = single("    assert_valid_invoice(inv)")
        self.assertIs(a.relation, R.OPAQUE)

    def test_ordinary_call_is_not_an_assertion(self):
        self.assertEqual(extract("def test_x():\n    setup_database()\n").tests[0].assertions, ())


class TestEffectiveStrength(unittest.TestCase):
    """Present-but-dead assertions verify nothing, however they are written."""

    def test_swallowed_by_bare_except(self):
        a = single("    try:\n        assert x == 1\n    except Exception:\n        pass")
        self.assertIs(a.relation, R.EQ)
        self.assertIs(a.effective, R.NONE)

    def test_not_swallowed_when_handler_does_something(self):
        a = single("    try:\n        assert x == 1\n    except Exception:\n        raise")
        self.assertIs(a.effective, R.EQ)

    def test_unreachable_after_return(self):
        self.assertIs(single("    return\n    assert x == 1").effective, R.NONE)

    def test_guarded_by_literal_false(self):
        self.assertIs(single("    if False:\n        assert x == 1").effective, R.NONE)

    def test_dynamic_condition_stays_reachable(self):
        self.assertIs(single("    if flag:\n        assert x == 1").effective, R.EQ)


class TestStructure(unittest.TestCase):
    def test_class_methods_are_qualified(self):
        result = extract("class TestThing:\n    def test_method(self):\n        assert x == 1\n")
        self.assertEqual(result.tests[0].qualname, "TestThing.test_method")

    def test_non_test_functions_are_ignored(self):
        self.assertEqual(extract("def helper():\n    assert x == 1\n").tests, ())

    def test_skip_markers_are_recorded(self):
        result = extract("@pytest.mark.skip\ndef test_x():\n    assert a == 1\n")
        self.assertEqual(len(result.tests[0].skip_markers), 1)

    def test_empty_body_is_detected(self):
        result = extract('def test_x():\n    """doc"""\n    pass\n')
        self.assertTrue(result.tests[0].is_empty)

    def test_subjects_keeps_the_strongest_relation_per_subject(self):
        result = extract("def test_x():\n    assert a is not None\n    assert a == 3\n")
        self.assertEqual(result.tests[0].subjects, {"a": R.EQ})

    def test_subjects_uses_effective_strength(self):
        result = extract(
            "def test_x():\n    try:\n        assert a == 3\n    except Exception:\n        pass\n"
        )
        self.assertEqual(result.tests[0].subjects, {"a": R.NONE})


class TestRobustness(unittest.TestCase):
    def test_syntax_error_is_reported_not_raised(self):
        result = extract("def test_x(:\n", filename="broken.py")
        self.assertFalse(result.ok)
        self.assertIn("broken.py", result.error)
        self.assertEqual(result.tests, ())

    def test_empty_source_is_clean(self):
        self.assertTrue(extract("").ok)


if __name__ == "__main__":
    unittest.main()
