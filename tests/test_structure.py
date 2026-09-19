"""Maintainability rules.

The motivating problem: an agent can emit a thousand lines that no human will
read line by line. These rules bound what one change may produce, and what the
resulting code may look like.

Differential by default — inherited debt is not this change's fault — with
`greenfield` making the limits absolute for a project starting clean.
"""

import unittest
from pathlib import Path

from yieldpoint.core.policy import Policy, Structure
from yieldpoint.core.structure import (
    CHANGE_TOO_LARGE,
    COMPLEXITY_TOO_HIGH,
    DUPLICATE_IMPLEMENTATION,
    FILE_TOO_LONG,
    FUNCTION_TOO_LONG,
    NESTING_TOO_DEEP,
    TOO_MANY_PARAMETERS,
    UTILITY_MODULE,
    check,
)
from yieldpoint.core.verdict import Status
from yieldpoint.verify import verify_change, verify_diff

GREENFIELD = Structure(greenfield=True)


def rules(before, after, path="src/app.py", config=GREENFIELD):
    return [f.rule for f in check(before, after, path, config)[0]]


def long_module(count):
    return "\n".join(f"def f{i}():\n    return {i}" for i in range(count)) + "\n"


class TestLimits(unittest.TestCase):
    def test_file_too_long(self):
        self.assertIn(FILE_TOO_LONG, rules(None, long_module(200)))

    def test_file_within_limit_is_silent(self):
        self.assertNotIn(FILE_TOO_LONG, rules(None, long_module(20)))

    def test_function_too_long(self):
        body = "\n".join(f"    x{i} = {i}" for i in range(60))
        self.assertIn(FUNCTION_TOO_LONG, rules(None, f"def f():\n{body}\n"))

    def test_too_many_parameters(self):
        self.assertIn(TOO_MANY_PARAMETERS, rules(None, "def f(a, b, c, d, e, g):\n    return a\n"))

    def test_nesting_too_deep(self):
        source = (
            "def f(a, b, c, d, e):\n"
            "    for x in a:\n        if b:\n            while c:\n"
            "                with d:\n                    if e:\n                        return x\n"
        )
        self.assertIn(NESTING_TOO_DEEP, rules(None, source))

    def test_complexity_too_high(self):
        branches = "\n".join(f"    if x == {i}:\n        return {i}" for i in range(12))
        self.assertIn(COMPLEXITY_TOO_HIGH, rules(None, f"def f(x):\n{branches}\n    return 0\n"))

    def test_utility_dump_module_names(self):
        for name in ("utils", "helpers", "misc", "common", "shared"):
            self.assertIn(UTILITY_MODULE, rules(None, "def a():\n    return 1\n", f"src/{name}.py"))

    def test_a_named_module_is_fine(self):
        self.assertNotIn(UTILITY_MODULE, rules(None, "def a():\n    return 1\n", "src/pricing.py"))


class TestChangeSize(unittest.TestCase):
    """The rule the whole feature exists for: output a human cannot review."""

    def test_a_large_addition_to_one_file_is_reported(self):
        self.assertIn(CHANGE_TOO_LARGE, rules(None, long_module(300)))

    def test_a_small_addition_is_silent(self):
        self.assertNotIn(CHANGE_TOO_LARGE, rules(long_module(100), long_module(110)))

    def test_it_is_about_the_diff_not_the_result(self):
        """A file already over its length limit may still receive a small edit."""
        before = long_module(250)
        after = before + "def extra():\n    return 1\n"
        self.assertNotIn(CHANGE_TOO_LARGE, rules(before, after, config=Structure()))

    def test_a_large_change_spread_across_files_is_caught(self):
        diff = "".join(
            f"--- /dev/null\n+++ b/src/m{i}.py\n@@ -0,0 +1,2 @@\n+def f{i}():\n+    return {i}\n"
            for i in range(40)
        )
        policy = Policy.from_dict({"structure": {"max_change_lines": 50}})
        verdict = verify_diff(diff, root=".", policy=policy, read=lambda rel: long_module(30))
        self.assertIn(CHANGE_TOO_LARGE, [f.rule for f in verdict.findings])

    def test_a_modest_change_set_is_silent(self):
        diff = "--- /dev/null\n+++ b/src/a.py\n@@ -0,0 +1,2 @@\n+def f():\n+    return 1\n"
        verdict = verify_diff(diff, root=".", policy=Policy(), read=lambda rel: "def f():\n    return 1\n")
        self.assertNotIn(CHANGE_TOO_LARGE, [f.rule for f in verdict.findings])


class TestDuplication(unittest.TestCase):
    DUPLICATED = '''
def compute_invoice(items, rate):
    total = 0
    for item in items:
        total += item.price * rate
    if total > 100:
        total = total * 0.9
    return total

def compute_order(lines, factor):
    amount = 0
    for line in lines:
        amount += line.cost * factor
    if amount > 100:
        amount = amount * 0.9
    return amount
'''

    def test_copy_paste_with_renamed_variables_is_found(self):
        """Shape is compared, not text, so renaming does not hide a duplicate."""
        self.assertIn(DUPLICATE_IMPLEMENTATION, rules(None, self.DUPLICATED))

    def test_short_functions_are_not_duplicates(self):
        source = "def a():\n    return 1\n\ndef b():\n    return 2\n"
        self.assertNotIn(DUPLICATE_IMPLEMENTATION, rules(None, source))

    def test_structurally_different_functions_are_not_duplicates(self):
        source = self.DUPLICATED.replace(
            "    if amount > 100:\n        amount = amount * 0.9\n", "")
        self.assertNotIn(DUPLICATE_IMPLEMENTATION, rules(None, source))

    def test_a_preexisting_duplicate_is_not_this_change_s_fault(self):
        after = self.DUPLICATED + "\ndef unrelated():\n    return 1\n"
        self.assertNotIn(
            DUPLICATE_IMPLEMENTATION, rules(self.DUPLICATED, after, config=Structure()))

    def test_it_can_be_disabled(self):
        config = Structure(greenfield=True, duplicate_implementation=None)
        self.assertNotIn(DUPLICATE_IMPLEMENTATION, rules(None, self.DUPLICATED, config=config))


class TestDifferential(unittest.TestCase):
    """Switching these on in an existing repository must not blame inherited debt."""

    def test_an_existing_violation_is_not_reported(self):
        self.assertEqual(rules(long_module(200), long_module(200), config=Structure()), [])

    def test_worsening_an_existing_violation_is_reported(self):
        self.assertIn(FILE_TOO_LONG, rules(long_module(200), long_module(210), config=Structure()))

    def test_improving_while_still_over_is_silent(self):
        self.assertNotIn(FILE_TOO_LONG, rules(long_module(210), long_module(200), config=Structure()))

    def test_greenfield_makes_the_limits_absolute(self):
        self.assertIn(FILE_TOO_LONG, rules(long_module(200), long_module(200), config=GREENFIELD))


class TestCustomRules(unittest.TestCase):
    """Teams add rules through configuration, never by naming code to run."""

    def policy(self, rule):
        return Policy.from_dict({"structure": {"custom": [rule]}})

    def test_forbid_call(self):
        policy = self.policy({"name": "no_print", "forbid_call": "print",
                              "message": "Use the logger."})
        verdict = verify_change(None, "def f():\n    print('x')\n", "src/a.py", policy)
        self.assertIn("no_print", [f.rule for f in verdict.findings])
        self.assertIn("Use the logger.", verdict.findings[0].detail)

    def test_forbid_import_matches_submodules(self):
        policy = self.policy({"name": "no_requests", "forbid_import": "requests"})
        verdict = verify_change(None, "import requests.adapters\n", "src/a.py", policy)
        self.assertIn("no_requests", [f.rule for f in verdict.findings])

    def test_require_name_pattern(self):
        policy = self.policy({"name": "test_naming", "path": "tests/**",
                              "require_name_pattern": "^test_"})
        bad = verify_change(None, "def check_this():\n    assert a == 1\n", "tests/t.py", policy)
        self.assertIn("test_naming", [f.rule for f in bad.findings])

    def test_path_scoping_limits_where_a_rule_applies(self):
        policy = self.policy({"name": "test_naming", "path": "tests/**",
                              "require_name_pattern": "^test_"})
        verdict = verify_change(None, "def check_this():\n    return 1\n", "src/a.py", policy)
        self.assertNotIn("test_naming", [f.rule for f in verdict.findings])

    def test_custom_severity(self):
        policy = self.policy({"name": "no_print", "forbid_call": "print",
                              "severity": "escalate"})
        verdict = verify_change(None, "def f():\n    print('x')\n", "src/a.py", policy)
        self.assertIs(verdict.status, Status.ESCALATE)

    def test_a_rule_without_a_name_is_dropped_with_a_warning(self):
        policy = Policy.from_dict({"structure": {"custom": [{"forbid_call": "print"}]}})
        self.assertEqual(policy.structure.custom, ())
        self.assertTrue(any("missing 'name'" in w for w in policy.warnings))


class TestConfiguration(unittest.TestCase):
    def test_thresholds_are_configurable(self):
        policy = Policy.from_dict({"structure": {"max_parameters": 10}})
        self.assertEqual(policy.structure.max_parameters, 10)

    def test_the_whole_family_can_be_turned_off(self):
        policy = Policy.from_dict({"structure": {"severity": "off"}})
        verdict = verify_change(None, long_module(300), "src/a.py", policy)
        self.assertEqual(verdict.findings, ())

    def test_defaults_follow_the_projects_own_standard(self):
        """RULES.md section 1 sets 300 lines; the default must match it."""
        self.assertEqual(Structure().max_file_lines, 300)
        self.assertFalse(Structure().greenfield)


class TestDogfooding(unittest.TestCase):
    def test_no_file_in_this_repository_exceeds_its_own_limit(self):
        config = Structure(greenfield=True)
        for path in sorted(Path("yieldpoint").rglob("*.py")):
            found = [f.rule for f in check(None, path.read_text(), str(path), config)[0]]
            self.assertNotIn(FILE_TOO_LONG, found, str(path))
            self.assertNotIn(UTILITY_MODULE, found, str(path))
            self.assertNotIn(DUPLICATE_IMPLEMENTATION, found, str(path))


if __name__ == "__main__":
    unittest.main()
