"""The examples have to keep working.

Documentation that no longer runs is worse than none: it is a confident,
wrong answer. The runnable examples are executed here, and the rest are at
least parsed and checked for the imports they claim to demonstrate.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"

#: Python puts the *script's* directory on ``sys.path``, not the working
#: directory — so an example run from ``examples/`` cannot import Yieldpoint
#: unless it is installed. The suite is meant to pass against a bare
#: interpreter with nothing installed, so the checkout is put on the path here.
ENV = {**os.environ, "PYTHONPATH": os.pathsep.join(
    [str(ROOT), os.environ.get("PYTHONPATH", "")]).rstrip(os.pathsep)}

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
                    cwd=str(ROOT), env=ENV,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertTrue(completed.stdout.strip(), "produced no output")

    def test_the_fanout_example_shows_pooling_fixes_it(self):
        """Its whole point is that isolated verification gets this wrong."""
        completed = subprocess.run(
            [sys.executable, str(EXAMPLES / "langgraph_fanout.py")],
            capture_output=True, text=True, timeout=180,
            cwd=str(ROOT), env=ENV,
        )
        isolated, pooled = completed.stdout.split("pooled change set:")
        # Asserting on the verdict, not the wording: the message for a moved-out
        # test has already been improved once, and a test that breaks on phrasing
        # teaches people to stop improving it.
        self.assertIn("repair", isolated, "isolated view should flag the move")
        self.assertNotIn("repair", pooled, "pooled view should not")


class TestIllustrativeExamples(unittest.TestCase):
    def test_they_parse(self):
        paths = sorted(EXAMPLES.glob("*.py"))
        self.assertTrue(paths, "no examples found — the glob, not the examples, broke")
        for path in paths:
            with self.subTest(path.name):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                self.assertTrue(tree.body, f"{path.name} parses to nothing")

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


class TestReadmeRendersEverywhere(unittest.TestCase):
    """The README is also the PyPI project page, and PyPI renders no diagrams.

    Mermaid blocks show as raw source there, and in most editor previews. A
    diagram nobody can see is worse than no diagram: it occupies the place
    where the explanation should have been.
    """

    README = EXAMPLES.parent / "README.md"

    def test_it_contains_no_mermaid(self):
        self.assertNotIn(
            "```mermaid", self.README.read_text(encoding="utf-8"),
            "PyPI and most editor previews render mermaid as raw text; "
            "use a ```text diagram instead",
        )

    def test_every_fence_is_closed(self):
        fences = re.findall(r"^```", self.README.read_text(encoding="utf-8"), re.M)
        self.assertEqual(len(fences) % 2, 0, "an unclosed code fence")

    def test_diagrams_fit_a_terminal(self):
        text = self.README.read_text(encoding="utf-8")
        for index, block in enumerate(re.findall(r"```text\n(.*?)```", text, re.S), 1):
            with self.subTest(diagram=index):
                widest = max((len(line) for line in block.splitlines()), default=0)
                self.assertLessEqual(widest, 96, "wraps in a narrow viewer")
