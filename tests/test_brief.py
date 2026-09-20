"""Telling an agent what is true before it edits.

A verdict arrives after the code is written, and fixing a rejected edit costs
another turn. Everything the verdict knows was knowable beforehand; these
tests are about saying it in time.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from yieldpoint.brief import brief
from yieldpoint.briefing import render, to_dict

POLICY = {
    "project": {"name": "Demo"},
    "test_contract": {"protected_patterns": ["**/tests/**", "**/test_*.py"]},
    "structure": {"max_file_lines": 40, "max_lines": 10, "max_parameters": 3,
                  "max_complexity": 5, "max_change_lines": 200},
    "boundaries": {"on_violation": "repair", "zones": [
        {"name": "core", "path": "src/core/**",
         "forbidden_imports": ["src.web", "requests"]}]},
}


class BriefCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def write(self, name: str, body: str) -> str:
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        return name

    def one(self, name: str):
        return brief([name], POLICY, self.root).files[0]


class TestItReportsHeadroom(BriefCase):
    def test_a_file_reports_the_lines_it_has_left(self):
        path = self.write("src/small.py", "def a():\n    return 1\n")
        entry = self.one(path)
        self.assertTrue(entry.exists)
        self.assertEqual(entry.line_limit, 40)
        self.assertGreater(entry.headroom, 30)

    def test_a_full_file_reports_no_headroom_rather_than_a_negative(self):
        path = self.write("src/big.py",
                          "".join(f"def f{i}():\n    return {i}\n" for i in range(40)))
        self.assertEqual(self.one(path).headroom, 0)

    def test_a_file_that_does_not_exist_yet_still_gets_a_budget(self):
        """A new file is exactly what tends to break a limit nobody mentioned."""
        entry = self.one("src/core/brand_new.py")
        self.assertFalse(entry.exists)
        self.assertEqual(entry.headroom, 40)
        self.assertEqual(entry.zone, "core")


class TestItNamesWhatIsAlreadyFull(BriefCase):
    def test_a_function_over_its_limit_is_called_out(self):
        body = "def wide(a, b, c, d, e):\n    return a\n"
        entry = self.one(self.write("src/wide.py", body))
        over = {c.measure: c for c in entry.crowded if c.over}
        self.assertIn("parameters", over, entry.crowded)
        self.assertEqual(over["parameters"].used, 5)
        self.assertEqual(over["parameters"].limit, 3)
        self.assertEqual(over["parameters"].name, "wide")

    def test_a_small_function_is_not_mentioned(self):
        entry = self.one(self.write("src/tiny.py", "def a(x):\n    return x\n"))
        self.assertEqual(entry.crowded, ())


class TestItListsProtectedAssertions(BriefCase):
    SOURCE = ("def test_total():\n    assert total == 42\n\n\n"
              "def test_name():\n    assert name == 'x'\n")

    def test_a_protected_file_lists_them_verbatim(self):
        """Counting them is not enough: an agent told "two assertions are
        protected" still has to guess which two."""
        entry = self.one(self.write("tests/test_x.py", self.SOURCE))
        self.assertTrue(entry.protected)
        self.assertIn("total == 42", " ".join(entry.assertions))

    def test_an_unprotected_file_lists_none(self):
        entry = self.one(self.write("src/plain.py", self.SOURCE))
        self.assertFalse(entry.protected)
        self.assertEqual(entry.assertions, ())


class TestItSaysNothingWhenThereIsNothingToSay(BriefCase):
    def test_a_plain_file_produces_a_single_line(self):
        path = self.write("src/plain.py", "def a():\n    return 1\n")
        text = render(brief([path], POLICY, self.root))
        self.assertIn("Nothing to watch", text)

    def test_no_paths_is_not_an_error(self):
        self.assertIn("nothing to brief", render(brief([], POLICY, self.root)))


class TestItMakesNoClaimItCannotSupport(BriefCase):
    def test_an_unparseable_file_says_so_rather_than_reporting_zero(self):
        """Reporting 300 lines of headroom for a file nothing could read
        would be the confident-wrong-answer this project exists to avoid."""
        entry = self.one(self.write("src/broken.py", "def ( oops\n"))
        self.assertEqual(entry.lines, 0)
        self.assertEqual(entry.crowded, ())
        self.assertNotEqual(entry.unreadable, "")

    def test_the_payload_round_trips(self):
        path = self.write("tests/test_x.py", "def test_a():\n    assert x == 1\n")
        payload = to_dict(brief([path], POLICY, self.root))
        self.assertEqual(payload["files"][0]["path"], path)
        self.assertTrue(payload["files"][0]["protected"])
        self.assertEqual(payload["change_budget_lines"], 200)


if __name__ == "__main__":
    unittest.main()
