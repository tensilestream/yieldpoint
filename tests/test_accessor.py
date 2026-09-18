"""Accessor equivalence: suppresses a false finding, never invents a true one."""

import unittest

from aegisflow.core.accessor import normalize, property_name
from aegisflow.core.policy import Policy
from aegisflow.core.verdict import Status
from aegisflow.verify import verify_change


class TestPropertyName(unittest.TestCase):
    def test_camel_case_prefixes(self):
        self.assertEqual(property_name("getTotal"), "total")
        self.assertEqual(property_name("isActive"), "active")
        self.assertEqual(property_name("hasItems"), "items")

    def test_snake_case_prefixes(self):
        self.assertEqual(property_name("get_total"), "total")
        self.assertEqual(property_name("is_active"), "active")

    def test_multi_word_property_keeps_its_shape(self):
        self.assertEqual(property_name("getTotalAmount"), "totalAmount")
        self.assertEqual(property_name("get_total_amount"), "total_amount")

    def test_non_accessors_return_none(self):
        for name in ("total", "compute", "getter", "island", "history", "get", "is"):
            self.assertIsNone(property_name(name), name)


class TestNormalize(unittest.TestCase):
    def test_getter_becomes_the_property(self):
        self.assertEqual(normalize("invoice.getTotal()"), "invoice.total")
        self.assertEqual(normalize("invoice.get_total()"), "invoice.total")

    def test_plain_attribute_is_unchanged(self):
        self.assertEqual(normalize("invoice.total"), "invoice.total")

    def test_bare_zero_arg_call_drops_the_parentheses(self):
        self.assertEqual(normalize("invoice.total()"), "invoice.total")

    def test_chains_are_normalised_throughout(self):
        self.assertEqual(normalize("order.getInvoice().getTotal()"), "order.invoice.total")

    def test_calls_with_arguments_are_not_accessors(self):
        """`inv.get(key)` is a lookup; treating it as a property would be wrong."""
        self.assertEqual(normalize("inv.get(key)"), "inv.get(key)")
        self.assertEqual(normalize("inv.getTotal(currency)"), "inv.getTotal(currency)")

    def test_free_functions_are_untouched(self):
        self.assertEqual(normalize("calc(1)"), "calc(1)")

    def test_subscripts_survive(self):
        self.assertEqual(normalize("items[0].getPrice()"), "items[0].price")

    def test_unparseable_input_degrades_to_itself(self):
        self.assertEqual(normalize("not valid python ("), "not valid python (")


class TestVerifyBehaviour(unittest.TestCase):
    PATH = "tests/test_invoice.py"

    def verdict(self, before, after, policy=None):
        return verify_change(before, after, self.PATH, policy or Policy())

    def test_field_to_getter_is_not_a_weakening(self):
        verdict = self.verdict(
            "def test_total():\n    assert inv.total == 42\n",
            "def test_total():\n    assert inv.getTotal() == 42\n",
        )
        self.assertIs(verdict.status, Status.PASS)

    def test_getter_to_field_is_not_a_weakening(self):
        verdict = self.verdict(
            "def test_total():\n    assert inv.getTotal() == 42\n",
            "def test_total():\n    assert inv.total == 42\n",
        )
        self.assertIs(verdict.status, Status.PASS)

    def test_python_property_to_method(self):
        verdict = self.verdict(
            "def test_total():\n    assert inv.total == 42\n",
            "def test_total():\n    assert inv.get_total() == 42\n",
        )
        self.assertIs(verdict.status, Status.PASS)

    def test_weakening_hidden_behind_an_accessor_rename_still_fires(self):
        """The suppression must not become a way to smuggle a downgrade past."""
        verdict = self.verdict(
            "def test_total():\n    assert inv.total == 42\n",
            "def test_total():\n    assert inv.getTotal() is not None\n",
        )
        self.assertIs(verdict.status, Status.REPAIR)
        self.assertIn("weakened", verdict.findings[0].detail)

    def test_a_genuinely_different_subject_still_fires(self):
        verdict = self.verdict(
            "def test_total():\n    assert inv.total == 42\n",
            "def test_total():\n    assert inv.subtotal == 42\n",
        )
        self.assertIs(verdict.status, Status.REPAIR)
        self.assertIn("removed", verdict.findings[0].detail)

    def test_removal_is_still_caught_when_the_accessor_form_is_absent(self):
        verdict = self.verdict(
            "def test_total():\n    assert inv.getTotal() == 42\n",
            "def test_total():\n    pass\n",
        )
        self.assertIsNot(verdict.status, Status.PASS)

    def test_can_be_disabled_by_policy(self):
        policy = Policy.from_dict({"subjects": {"accessor_equivalence": False}})
        verdict = self.verdict(
            "def test_total():\n    assert inv.total == 42\n",
            "def test_total():\n    assert inv.getTotal() == 42\n",
            policy,
        )
        self.assertIs(verdict.status, Status.REPAIR)

    def test_enabled_by_default(self):
        self.assertTrue(Policy().subjects.accessor_equivalence)

    def test_composes_with_parametrisation(self):
        """Both normalisations apply: accessor rewrite plus parametrised rewrite."""
        header = "import pytest\nfrom app import calc\n\n"
        verdict = self.verdict(
            header + "def test_one():\n    assert calc(1).total == 2\n",
            header + '@pytest.mark.parametrize("n,e", [(1, 2)])\n'
            "def test_calc(n, e):\n    assert calc(n).getTotal() == e\n",
        )
        self.assertIs(verdict.status, Status.PASS)


if __name__ == "__main__":
    unittest.main()
