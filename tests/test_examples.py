"""The examples have to keep working.

Documentation that no longer runs is worse than none: it is a confident,
wrong answer. The runnable examples are executed here, and the rest are at
least parsed and checked for the imports they claim to demonstrate.
"""

from __future__ import annotations

import ast
import subprocess
import sys
import unittest
from pathlib import Path

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"

#: Examples that run standalone, with no third-party framework installed.
RUNNABLE = ("plain_loop.py", "eval_harness.py", "langgraph_fanout.py",
            "harness_middleware.py")

#: Examples that demonstrate an integration and import it lazily.
ILLUSTRATIVE = (
    "openai_agents_tool.py", "crewai_guard.py",
    "claude_agent_sdk_hook.py", "pytest_conftest.py",
)


class TestRunnableExamples(unittest.TestCase):
    def test_they_run_and_exit_clean(self):
        for name in RUNNABLE:
            with self.subTest(name):
                completed = subprocess.run(
                    [sys.executable, str(EXAMPLES / name)],
                    capture_output=True, text=True, timeout=180,
                    cwd=str(EXAMPLES.parent),
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertTrue(completed.stdout.strip(), "produced no output")

    def test_the_fanout_example_shows_pooling_fixes_it(self):
        """Its whole point is that isolated verification gets this wrong."""
        completed = subprocess.run(
            [sys.executable, str(EXAMPLES / "langgraph_fanout.py")],
            capture_output=True, text=True, timeout=180, cwd=str(EXAMPLES.parent),
        )
        isolated, pooled = completed.stdout.split("pooled change set:")
        self.assertIn("was removed", isolated, "isolated view should flag the move")
        self.assertNotIn("was removed", pooled, "pooled view should not")


class TestIllustrativeExamples(unittest.TestCase):
    def test_they_parse(self):
        for path in EXAMPLES.glob("*.py"):
            with self.subTest(path.name):
                ast.parse(path.read_text(encoding="utf-8"))

    def test_they_import_only_lazily(self):
        """A framework import at module level would break `python -c 'import'`."""
        for name in ILLUSTRATIVE:
            with self.subTest(name):
                tree = ast.parse((EXAMPLES / name).read_text(encoding="utf-8"))
                for node in tree.body:
                    if isinstance(node, (ast.Import, ast.ImportFrom)):
                        module = getattr(node, "module", "") or ""
                        self.assertFalse(
                            module.split(".")[0] in {"agents", "crewai", "langgraph",
                                                     "claude_agent_sdk"},
                            f"{name} imports {module} at module level",
                        )

    def test_every_example_is_listed_in_the_readme(self):
        listed = (EXAMPLES / "README.md").read_text(encoding="utf-8")
        for path in sorted(EXAMPLES.iterdir()):
            if path.name == "README.md":
                continue
            with self.subTest(path.name):
                self.assertIn(path.name, listed, f"{path.name} is not in the index")


if __name__ == "__main__":
    unittest.main()
