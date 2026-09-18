"""Refactor integrity.

Test tampering weakens what is verified; a broken refactor leaves code that
still parses and no longer resolves. The motivating case is real: while splitting
a module in this repository, a definition was renamed and a call site was left
behind. The suite caught it — but only because that code had tests, and only
after running them. This catches it before the edit is applied.
"""

import unittest

from aegisflow.core.policy import Policy
from aegisflow.core.refactor import DANGLING_REFERENCE, EXPORT_REMOVED, check
from aegisflow.core.symbols import scan
from aegisflow.core.verdict import Status
from aegisflow.verify import verify_change, verify_diff


def rules(before, after, path="src/module.py", **kwargs):
    return [f.rule for f in check(before, after, path, **kwargs)[0]]


class TestTheRealBug(unittest.TestCase):
    """Reconstructed from the actual failure, in both its halves."""

    def test_renamed_definition_with_a_stale_call_site(self):
        before = (
            "def _from_assert(stmt, reachable):\n    return []\n\n"
            "def _scan_stmt(stmt, out):\n    out.extend(_from_assert(stmt, True))\n"
        )
        after = (
            "from .recognise import from_assert\n\n"
            "def _scan_stmt(stmt, out):\n    out.extend(_from_assert(stmt, True))\n"
        )
        self.assertEqual(rules(before, after), [DANGLING_REFERENCE])

    def test_function_moved_to_the_wrong_module(self):
        before = "def _monotonicity(a):\n    return []\n\ndef verify():\n    return _monotonicity(1)\n"
        after = "def verify():\n    return _monotonicity(1)\n"
        self.assertEqual(rules(before, after), [DANGLING_REFERENCE])

    def test_a_correct_move_is_silent(self):
        before = (
            "def _from_assert(stmt):\n    return []\n\n"
            "def _scan_stmt(stmt, out):\n    out.extend(_from_assert(stmt))\n"
        )
        after = (
            "from .recognise import from_assert\n\n"
            "def _scan_stmt(stmt, out):\n    out.extend(from_assert(stmt))\n"
        )
        self.assertEqual(rules(before, after), [])


class TestLegacyToFunctional(unittest.TestCase):
    """Converting classes to functions is a refactor, and must be checkable."""

    LEGACY = (
        "class InvoiceCalculator:\n"
        "    def __init__(self, rate):\n        self.rate = rate\n\n"
        "    def total(self, qty, price):\n        return qty * price * self.rate\n\n\n"
        "def report(qty, price):\n"
        "    return InvoiceCalculator(1.2).total(qty, price)\n"
    )

    def test_a_complete_conversion_is_silent(self):
        functional = (
            "def total(rate, qty, price):\n    return qty * price * rate\n\n\n"
            "def report(qty, price):\n    return total(1.2, qty, price)\n"
        )
        self.assertEqual(rules(self.LEGACY, functional), [])

    def test_a_conversion_that_misses_a_call_site_is_caught(self):
        half_done = (
            "def total(rate, qty, price):\n    return qty * price * rate\n\n\n"
            "def report(qty, price):\n"
            "    return InvoiceCalculator(1.2).total(qty, price)\n"
        )
        findings = check(self.LEGACY, half_done, "src/invoice.py")[0]
        self.assertEqual([f.rule for f in findings], [DANGLING_REFERENCE])
        self.assertEqual(findings[0].symbol, "InvoiceCalculator")

    def test_converting_to_a_pipeline_style_is_silent(self):
        pipeline = (
            "from functools import reduce\n\n"
            "def total(rate, qty, price):\n    return reduce(lambda a, b: a * b, [qty, price, rate])\n\n\n"
            "def report(qty, price):\n    return total(1.2, qty, price)\n"
        )
        self.assertEqual(rules(self.LEGACY, pipeline), [])


class TestDifferential(unittest.TestCase):
    def test_a_preexisting_dangling_name_is_not_this_change_s_fault(self):
        before = "def f():\n    return undefined_helper()\n"
        after = "def f():\n    return undefined_helper()\n\ndef g():\n    return 1\n"
        self.assertEqual(rules(before, after), [])

    def test_a_newly_introduced_dangling_name_is_reported(self):
        before = "def f():\n    return 1\n"
        after = "def f():\n    return missing_helper()\n"
        self.assertEqual(rules(before, after), [DANGLING_REFERENCE])

    def test_a_new_file_is_checked_in_full(self):
        self.assertEqual(rules(None, "def f():\n    return nope()\n"), [DANGLING_REFERENCE])


class TestNoFalsePositives(unittest.TestCase):
    """The scanner over-approximates bindings; these must all stay silent."""

    def assertClean(self, source):
        self.assertEqual(rules(None, source), [], source)

    def test_parameters_locals_and_comprehensions(self):
        self.assertClean("def f(a, *rest, **kw):\n    b = a\n    return [x for x in rest] + [b] + list(kw)\n")

    def test_imports_in_every_form(self):
        self.assertClean("import os\nimport os.path as p\nfrom sys import argv\n\ndef f():\n    return os, p, argv\n")

    def test_with_for_and_except_bindings(self):
        self.assertClean(
            "def f(items):\n"
            "    for i in items:\n        print(i)\n"
            "    with open('x') as handle:\n        handle.read()\n"
            "    try:\n        pass\n    except ValueError as exc:\n        return exc\n"
        )

    def test_builtins_and_dunders(self):
        self.assertClean("def f():\n    return len([1]) if __name__ else ValueError\n")

    def test_class_attributes_and_self(self):
        self.assertClean("class A:\n    x = 1\n\n    def m(self):\n        return self.x\n")

    def test_walrus_and_lambda(self):
        self.assertClean("def f(xs):\n    g = lambda y: y + 1\n    if (n := len(xs)):\n        return g(n)\n    return 0\n")

    def test_star_import_disables_the_check(self):
        findings, skipped = check(None, "from x import *\n\ndef f():\n    return anything()\n", "m.py")
        self.assertEqual(findings, [])
        self.assertIn("import *", skipped[0])

    def test_the_whole_real_codebase_is_clean(self):
        """Any hit here is a false positive on production code."""
        from pathlib import Path

        for path in sorted(Path("aegisflow").rglob("*.py")):
            self.assertEqual(scan(path.read_text(), filename=str(path)).dangling(), (), str(path))


class TestExports(unittest.TestCase):
    BEFORE = "__all__ = ['alpha', 'beta']\n\ndef alpha():\n    pass\n\ndef beta():\n    pass\n"

    def test_dropping_a_public_name_is_reported(self):
        after = "__all__ = ['alpha']\n\ndef alpha():\n    pass\n"
        self.assertEqual(rules(self.BEFORE, after), [EXPORT_REMOVED])

    def test_a_name_still_defined_is_not_reported(self):
        after = "__all__ = ['alpha']\n\ndef alpha():\n    pass\n\ndef beta():\n    pass\n"
        self.assertEqual(rules(self.BEFORE, after), [])

    def test_a_name_moved_elsewhere_in_the_change_set_is_not_reported(self):
        after = "__all__ = ['alpha']\n\ndef alpha():\n    pass\n"
        self.assertEqual(rules(self.BEFORE, after, also_defined={"beta"}), [])

    def test_a_module_without_all_is_not_second_guessed(self):
        self.assertEqual(rules("def alpha():\n    pass\n", "def gamma():\n    pass\n"), [])


class TestIntegration(unittest.TestCase):
    def test_source_files_are_now_verified(self):
        """Refactors live in source, where the verifier used to be silent."""
        verdict = verify_change(
            "def helper():\n    return 1\n\ndef f():\n    return helper()\n",
            "def f():\n    return helper()\n",
            "src/app.py", Policy(),
        )
        self.assertIs(verdict.status, Status.REPAIR)
        self.assertEqual(verdict.findings[0].rule, DANGLING_REFERENCE)

    def test_rules_can_be_disabled(self):
        policy = Policy.from_dict({"refactor": {"dangling_reference": "off"}})
        verdict = verify_change(None, "def f():\n    return nope()\n", "src/app.py", policy)
        self.assertEqual(verdict.findings, ())

    def test_severity_is_configurable(self):
        policy = Policy.from_dict({"refactor": {"dangling_reference": "escalate"}})
        verdict = verify_change(None, "def f():\n    return nope()\n", "src/app.py", policy)
        self.assertIs(verdict.status, Status.ESCALATE)

    def test_moving_a_definition_between_files_is_not_an_export_loss(self):
        diff = (
            "--- a/src/a.py\n+++ b/src/a.py\n@@ -1,4 +1,2 @@\n"
            " __all__ = ['moved']\n-\n-def moved():\n-    pass\n+from .b import moved\n"
        )
        verdict = verify_diff(diff, root="/nonexistent", policy=Policy())
        self.assertEqual([f.rule for f in verdict.findings], [])


if __name__ == "__main__":
    unittest.main()
