"""The README's language table must match what the engine actually does.

A support matrix that drifts is worse than none: it is a confident, wrong
answer about somebody's language. These tests read the table out of README.md
and re-measure every row.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from language_matrix import CASES, measure  # noqa: E402

README = ROOT / "README.md"


def _table_rows() -> dict[str, str]:
    """Language -> the README's row for it."""
    text = README.read_text(encoding="utf-8")
    # Split on the horizontal rule, not on "---": the table's own separator
    # row is full of dashes and would truncate the section before any data.
    section = text.split("### Languages", 1)[-1].split("\n---\n", 1)[0]
    rows = {}
    for line in section.splitlines():
        if not line.startswith("| ") or line.startswith("| Language") or "---" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        rows[cells[0]] = line
    return rows


class TestEveryLanguageIsMeasured(unittest.TestCase):
    def test_a_caught_weakening_is_also_quiet_on_legitimate_work(self):
        """Half a detector is not support. A checker that fires on an
        unchanged file would be turned off within a week."""
        for case in CASES:
            with self.subTest(language=case.language):
                row = measure(case)
                if row.caught:
                    self.assertTrue(row.quiet_on_legitimate, case.language)

    def test_only_python_claims_it_can_block(self):
        """Lexical findings may advise. Letting one block would break the
        guarantee that a blocked build was decided by a parser."""
        for case in CASES:
            with self.subTest(language=case.language):
                row = measure(case)
                if row.tier == "exact":
                    self.assertEqual(case.language, "Python")


class TestTheReadmeMatchesReality(unittest.TestCase):
    def test_every_case_has_a_row(self):
        rows = _table_rows()
        for case in CASES:
            self.assertIn(case.language, rows, f"{case.language} missing from README")

    def test_no_row_claims_more_than_the_engine_does(self):
        rows = _table_rows()
        for case in CASES:
            with self.subTest(language=case.language):
                row, line = measure(case), rows.get(case.language, "")
                claims_caught = re.search(r"\|\s*yes\s*\|", line) is not None
                if not row.caught:
                    self.assertIn("**no**", line,
                                  f"{case.language} is not read, but the README "
                                  "does not say so")
                else:
                    self.assertTrue(claims_caught, case.language)

    def test_the_table_says_which_can_gate(self):
        rows = _table_rows()
        for case in CASES:
            with self.subTest(language=case.language):
                line = rows[case.language]
                tier = measure(case).tier
                if tier == "exact":
                    self.assertIn("**yes**", line)
                else:
                    self.assertNotIn("| **yes** |", line)


if __name__ == "__main__":
    unittest.main()
