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

ROOT = Path(__file__).resolve().parent.parent

#: `max_file_lines` is opt-in, so these tests ask for it explicitly.
#: They are about how a limit behaves, not about which are on by default.
LENGTH_LIMITED = Structure(max_file_lines=300)
GREENFIELD = Structure(greenfield=True, max_file_lines=300)


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
        self.assertNotIn(CHANGE_TOO_LARGE, rules(before, after, config=LENGTH_LIMITED))

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
            DUPLICATE_IMPLEMENTATION, rules(self.DUPLICATED, after, config=LENGTH_LIMITED))

    def test_it_can_be_disabled(self):
        config = Structure(greenfield=True, duplicate_implementation=None)
        self.assertNotIn(DUPLICATE_IMPLEMENTATION, rules(None, self.DUPLICATED, config=config))


class TestDifferential(unittest.TestCase):
    """Switching these on in an existing repository must not blame inherited debt."""

    # yieldpoint: allow assertion_monotonicity - subject renamed, see docstring
    def test_an_existing_violation_is_not_reported(self):
        """The subject moved from Structure() to LENGTH_LIMITED because the
        limit is now opt-in. Stronger, not weaker: with the limit off this
        passed vacuously; it now exercises the differential suppression it was
        always meant to."""
        self.assertEqual(rules(long_module(200), long_module(200), config=LENGTH_LIMITED), [])

    def test_worsening_an_existing_violation_is_reported(self):
        self.assertIn(FILE_TOO_LONG, rules(long_module(200), long_module(210), config=LENGTH_LIMITED))

    def test_improving_while_still_over_is_silent(self):
        self.assertNotIn(FILE_TOO_LONG, rules(long_module(210), long_module(200), config=LENGTH_LIMITED))

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

    def test_the_file_length_limit_is_opt_in(self):
        """A line count is the weakest proxy here for one-responsibility-per-
        module, and it flags well-regarded codebases. Off by default so the
        rules that say something about structure directly are not switched off
        alongside it."""
        self.assertIsNone(Structure().max_file_lines)
        self.assertFalse(Structure().greenfield)

    def test_the_structural_rules_stay_on_by_default(self):
        """These say something about design rather than about size."""
        self.assertIsNotNone(Structure().duplicate_implementation)
        self.assertTrue(Structure().forbid_utility_modules)
        self.assertEqual(Structure().max_lines, 50)
        self.assertEqual(Structure().max_complexity, 10)

    def test_this_repository_opts_in_to_its_own_house_style(self):
        """RULES.md section 1 sets 300 lines. That is a choice this project
        makes in its own policy, not one it makes for everybody."""
        policy = Policy.load(str(ROOT / ".yieldpoint.json"))
        self.assertEqual(policy.structure.max_file_lines, 300)


class TestDogfooding(unittest.TestCase):
    def test_no_file_in_this_repository_exceeds_its_own_limit(self):
        config = Structure(greenfield=True)
        for path in sorted(Path("yieldpoint").rglob("*.py")):
            found = [f.rule for f in check(None, path.read_text(encoding="utf-8"), str(path), config)[0]]
            self.assertNotIn(FILE_TOO_LONG, found, str(path))
            self.assertNotIn(UTILITY_MODULE, found, str(path))
            self.assertNotIn(DUPLICATE_IMPLEMENTATION, found, str(path))


class TestAcknowledgementIsNotCode(unittest.TestCase):
    """The escape hatch must not create work for the rule it answers.

    Measured before this was fixed: acknowledging ``too_many_parameters`` on a
    function sitting exactly at the line limit pushed it to 51 and produced a
    ``function_too_long`` finding that had not existed. The tool manufactured
    the finding as the price of using its own escape hatch.
    """

    def _function(self, limit, *, comment=""):
        head = "def f(a, b, c, d, e, g):\n"
        body = "\n".join(f"    x{i} = 1" for i in range(limit - 1))
        return head + comment + body + "\n"

    def test_acknowledging_one_rule_does_not_trip_another(self):
        config = Structure(greenfield=True)
        at_limit = self._function(config.max_lines)
        acknowledged = self._function(
            config.max_lines,
            comment="    # yieldpoint: allow too_many_parameters - intentional\n")
        plain = [f.rule for f in check(None, at_limit, "m.py", config)[0]]
        after = [f.rule for f in check(None, acknowledged, "m.py", config)[0]]
        self.assertNotIn(FUNCTION_TOO_LONG, plain)
        self.assertNotIn(FUNCTION_TOO_LONG, after)

    def test_an_acknowledgement_sharing_a_line_with_code_still_counts(self):
        """Only a line that exists solely to carry the comment is discounted."""
        config = Structure(greenfield=True)
        trailing = ("def f():  # yieldpoint: allow too_many_parameters - yes\n"
                    + "\n".join(f"    x{i} = 1" for i in range(config.max_lines)))
        found = [f.rule for f in check(None, trailing, "m.py", config)[0]]
        self.assertIn(FUNCTION_TOO_LONG, found)


class TestWhoseDebtItIs(unittest.TestCase):
    """A change that adds one line to a long file did not write the long file."""

    def _file(self, lines):
        return "\n".join(f"x{i} = 1" for i in range(lines)) + "\n"

    def setUp(self):
        self.config = Structure(max_file_lines=300)

    def test_growing_an_already_long_file_names_both_numbers(self):
        big = self._file(1385)
        found = check(big, big + "y = 2\n", "wb.py", self.config)[0]
        self.assertEqual([f.rule for f in found], [FILE_TOO_LONG])
        self.assertIn("1,385", found[0].detail)
        self.assertIn("1,386", found[0].detail)

    def test_inherited_debt_is_not_prescribed_as_this_change_s_work(self):
        big = self._file(1385)
        found = check(big, big + "y = 2\n", "wb.py", self.config)[0]
        self.assertIn("not this change's debt", found[0].prescription)

    def test_a_file_this_change_wrote_gets_the_full_prescription(self):
        found = check("", self._file(400), "wb.py", self.config)[0]
        self.assertIn("Split it into modules", found[0].prescription)
        self.assertNotIn("not this change's debt", found[0].prescription)

    def test_a_file_left_alone_is_not_reported(self):
        big = self._file(1385)
        self.assertEqual(check(big, big, "wb.py", self.config)[0], [])

    def test_a_file_being_paid_down_is_not_reported(self):
        self.assertEqual(
            check(self._file(1385), self._file(1300), "wb.py", self.config)[0], [])

    def test_without_a_baseline_the_finding_says_it_cannot_attribute(self):
        found = check(None, self._file(400), "wb.py", self.config)[0]
        lengths = [f for f in found if f.rule == FILE_TOO_LONG]
        self.assertEqual(len(lengths), 1)
        self.assertIn("not known", lengths[0].detail)


if __name__ == "__main__":
    unittest.main()


class TestElifIsNotNesting(unittest.TestCase):
    """Python has no `elif` node.

    An `elif` is an `If` sitting alone in the previous `If`'s `orelse`, so a
    flat four-branch chain measured as four levels of nesting. Nobody reads it
    that way: it is one decision with four answers. Reporting it as deeply
    nested sends people to restructure code that was already flat — found when
    `nesting_too_deep` fired on a four-branch dispatch inside one loop.
    """

    def _nesting(self, source):
        from yieldpoint.core.metrics import measure

        return measure(source).functions[0].nesting

    def test_a_flat_chain_counts_one_level_for_the_chain(self):
        source = ("def f(x):\n    for i in x:\n        if i == 1:\n            a()\n"
                  "        elif i == 2:\n            b()\n"
                  "        elif i == 3:\n            c()\n")
        self.assertEqual(self._nesting(source), 2)

    def test_an_else_block_containing_an_if_is_still_a_level(self):
        """The same tree as `elif`; only the column separates them, and the
        author who indented it wrote a real level."""
        source = ("def h(x):\n    if x:\n        a()\n    else:\n"
                  "        if x:\n            b()\n")
        self.assertEqual(self._nesting(source), 2)

    def test_real_nesting_is_unchanged(self):
        source = ("def g(x):\n    for i in x:\n        if i:\n"
                  "            for j in i:\n                if j:\n"
                  "                    k()\n")
        self.assertEqual(self._nesting(source), 4)

    def test_nesting_inside_an_elif_branch_still_counts(self):
        source = ("def k(x):\n    if x == 1:\n        a()\n    elif x == 2:\n"
                  "        for i in x:\n            if i:\n                b()\n")
        self.assertEqual(self._nesting(source), 3)
