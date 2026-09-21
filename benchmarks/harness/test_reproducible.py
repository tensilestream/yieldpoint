"""Two identical runs must produce identical tool results.

Every arm runs in a fresh temp checkout with a random name, and that name
reaches the model through tool output — pytest paths, tracebacks, import
errors. If any of it varies, the two arms of an A/B see different context and
diverge from the first difference onward. The comparison then measures the
divergence rather than the thing under test.

This is the check that has to pass before any harness figure is publishable.
It needs no model: the question is whether the *inputs* a model would see are
identical, and that is decidable here.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from langgraph_agent import CheckoutTools  # noqa: E402

FILES = {
    "calc.py": "def total(subtotal, vat):\n    return subtotal\n",
    "test_calc.py": "from calc import total\n\n\ndef test_total():\n    assert total(100, 0.2) == 120\n",
    "pkg/__init__.py": "",
    "pkg/util.py": "VALUE = 1\n",
    "pkg/deep/more.py": "OTHER = 2\n",
}


def checkout() -> Path:
    root = Path(tempfile.mkdtemp())
    for name, body in FILES.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body)
    return root


class ReproducibleCase(unittest.TestCase):
    def setUp(self):
        self.roots = [checkout(), checkout()]
        for root in self.roots:
            self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        self.tools = [CheckoutTools(str(r), "python3 -m pytest -q") for r in self.roots]

    def _both(self, name: str, arguments: dict) -> tuple[str, str]:
        return tuple(tool.call(name, arguments, []) for tool in self.tools)

    def test_reading_a_file_is_identical_across_checkouts(self):
        first, second = self._both("read_file", {"path": "calc.py"})
        self.assertEqual(first, second)
        self.assertEqual(first, FILES["calc.py"])

    def test_listing_files_is_identical_across_checkouts(self):
        """Glob order is filesystem-dependent, so it must be imposed here."""
        first, second = self._both("list_files", {"glob": "**/*.py"})
        self.assertEqual(first, second)
        # Equality alone passed on APFS by luck: glob happened to be stable
        # there. Asserting the order makes the property hold by construction
        # on any filesystem, which is what "reproducible" actually needs.
        self.assertEqual(first.splitlines(),
                         ["calc.py", "pkg/__init__.py", "pkg/deep/more.py",
                          "pkg/util.py", "test_calc.py"])

    def test_listing_files_is_identical_on_repeat_within_one_checkout(self):
        tool = self.tools[0]
        self.assertEqual(tool.call("list_files", {"glob": "**/*.py"}, []),
                         tool.call("list_files", {"glob": "**/*.py"}, []))

    def test_no_checkout_path_survives_into_a_tool_result(self):
        """The random directory name is what made two runs diverge."""
        for tool, root in zip(self.tools, self.roots):
            text = tool.call("list_files", {"glob": "**/*"}, [])
            self.assertNotIn(str(root), text)
            self.assertNotIn(root.name, text)

    def test_a_failing_test_run_is_identical_across_checkouts(self):
        first, second = self._both("run_tests", {})
        self.assertEqual(first, second)
        self.assertIn("exit=", first)

    def test_repeated_runs_of_one_suite_are_identical(self):
        """The duration varies run to run and reaches the model verbatim.

        Measured at 0.055s and 0.056s across five runs of one unchanged suite
        before this was normalised, which is enough to make two arms of an A/B
        diverge from that point on.
        """
        slow = self.roots[0] / "test_slow.py"
        slow.write_text("import unittest\n\n\nclass T(unittest.TestCase):\n"
                        "    def test_a(self):\n        sum(range(6_000_000))\n"
                        "        self.assertEqual(1, 2)\n")
        tool = CheckoutTools(str(self.roots[0]), "python3 -m unittest discover -q 2>&1")
        runs = {tool.call("run_tests", {}, []) for _ in range(5)}
        self.assertEqual(len(runs), 1, "five runs of one suite were not identical")
        self.assertIn("in 0.000s", runs.pop())

    def test_durations_are_normalised_in_either_runner_format(self):
        tool = self.tools[0]
        self.assertEqual(tool._stable("Ran 3 tests in 1.234s"), "Ran 3 tests in 0.000s")
        self.assertEqual(tool._stable("== 1 failed, 2 passed in 0.12s =="),
                         "== 1 failed, 2 passed in 0.000s ==")

    def test_an_error_mentioning_the_path_is_normalised(self):
        for tool in self.tools:
            text = tool._stable(f"Traceback: {tool.root}/pkg/util.py line 1")
            self.assertEqual(text, "Traceback: /workspace/pkg/util.py line 1")


if __name__ == "__main__":
    unittest.main()
