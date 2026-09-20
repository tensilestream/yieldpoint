"""DRY across files, which one file at a time cannot see.

The copy that hurts is the one in another module: nobody reading either file
can see the other, so the two drift, and a fix applied to one is a bug left in
the other.
"""

from __future__ import annotations

import unittest

from yieldpoint.core import duplication
from yieldpoint.core.verdict import Status

BODY = ("    total = 0\n    for row in rows:\n        if row.active:\n"
        "            total += row.amount\n    return total\n")
TINY = "    return x + 1\n"


def states(*files):
    return [(path, None, source) for path, source in files]


class TestItFindsTheCopyInAnotherFile(unittest.TestCase):
    def _rules(self, *files, severity=Status.REPAIR):
        return duplication.check(states(*files), severity)

    def test_the_same_shape_in_two_files_is_reported(self):
        found = self._rules(("src/invoices.py", f"def sum_invoices(rows):\n{BODY}"),
                            ("src/payments.py", f"def sum_payments(rows):\n{BODY}"))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].file, "src/payments.py")
        self.assertIn("src/invoices.py", found[0].detail)

    def test_renamed_variables_do_not_hide_it(self):
        """Shape, not text: a copy-paste that renamed things is still a copy."""
        other = BODY.replace("total", "running").replace("row", "item")
        found = self._rules(("src/a.py", f"def one(rows):\n{BODY}"),
                            ("src/b.py", f"def two(items):\n{other}"))
        self.assertEqual(len(found), 1)

    def test_two_copies_in_one_file_are_left_to_structure(self):
        """structure.py already owns that case; reporting twice is noise."""
        self.assertEqual(
            self._rules(("src/a.py", f"def one(rows):\n{BODY}\n\ndef two(rows):\n{BODY}")),
            [])

    def test_unrelated_functions_are_silent(self):
        self.assertEqual(
            self._rules(("src/a.py", f"def one(rows):\n{BODY}"),
                        ("src/b.py", "def other(x):\n    return x * 3\n")),
            [])

    def test_short_functions_are_coincidence_not_duplication(self):
        self.assertEqual(
            self._rules(("src/a.py", f"def one(x):\n{TINY}"),
                        ("src/b.py", f"def two(x):\n{TINY}")),
            [])

    def test_a_deleted_file_contributes_nothing(self):
        self.assertEqual(
            duplication.check([("src/a.py", f"def one(rows):\n{BODY}", None),
                               ("src/b.py", None, f"def two(rows):\n{BODY}")],
                              Status.REPAIR),
            [])

    def test_switching_the_rule_off_silences_it(self):
        self.assertEqual(
            self._rules(("src/a.py", f"def one(rows):\n{BODY}"),
                        ("src/b.py", f"def two(rows):\n{BODY}"), severity=None),
            [])

    def test_an_unparseable_file_is_skipped_not_guessed_at(self):
        self.assertEqual(
            self._rules(("src/a.py", f"def one(rows):\n{BODY}"),
                        ("src/broken.py", "def ( oops\n")),
            [])

    def test_the_report_is_stable_across_runs(self):
        """Findings are sorted by a stable key, so output does not depend on
        dict iteration order (RULES.md section 4)."""
        files = (("src/z.py", f"def z(rows):\n{BODY}"),
                 ("src/a.py", f"def a(rows):\n{BODY}"),
                 ("src/m.py", f"def m(rows):\n{BODY}"))
        first = [(f.file, f.symbol) for f in self._rules(*files)]
        second = [(f.file, f.symbol) for f in self._rules(*files)]
        self.assertEqual(first, second)
        self.assertEqual(len(first), 2)


class TestOnlyPythonIsRead(unittest.TestCase):
    def test_a_language_with_no_parser_is_left_alone(self):
        self.assertEqual(
            duplication.check(states(("src/a.ts", "function one() { return 1; }"),
                                     ("src/b.ts", "function two() { return 1; }")),
                              Status.REPAIR),
            [])


if __name__ == "__main__":
    unittest.main()
