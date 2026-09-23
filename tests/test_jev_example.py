"""Optional Jev examples must remain useful without credentials or network."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class TestJevExample(unittest.TestCase):
    def test_default_python_example_uses_deterministic_fallback(self):
        environment = {key: value for key, value in os.environ.items() if not key.startswith("JEV_")}
        environment.pop("YIELDPOINT_ENABLE_JEV", None)
        result = subprocess.run(
            [sys.executable, "examples/jev_router.py"], cwd=ROOT, env=environment,
            capture_output=True, text=True, check=True,
        )
        output = json.loads(result.stdout)
        self.assertEqual(output["source"], "deterministic")
        self.assertEqual(output["model"], "capable")

    def test_the_example_shows_a_router_answer_being_refused_by_the_gate(self):
        """Confidence is an input, not an authorization. The example has to show
        that, or a reader copies the selection half and skips the check."""
        environment = {key: value for key, value in os.environ.items() if not key.startswith("JEV_")}
        environment.pop("YIELDPOINT_ENABLE_JEV", None)
        result = subprocess.run(
            [sys.executable, "examples/jev_router.py"], cwd=ROOT, env=environment,
            capture_output=True, text=True, check=True,
        )
        handoff = json.loads(result.stdout)["handoff"]
        self.assertFalse(handoff["allowed"])
        self.assertIn("lacks required capability", handoff["reason"])

    def test_the_node_example_applies_the_same_gate(self):
        """Runs the example rather than trusting it: an example that no longer
        executes is worse than no example, because it reads as current."""
        if not shutil.which("node"):
            self.skipTest("node is not installed")
        result = subprocess.run(
            ["node", "examples/node/jev_router.mjs"], cwd=ROOT,
            capture_output=True, text=True, check=True,
        )
        output = json.loads(result.stdout)
        self.assertEqual(output["model"], "capable")
        self.assertFalse(output["refused"]["allowed"])
        self.assertIn("lacks required capability", output["refused"]["reason"])
        self.assertEqual(output["allowed"]["reason"],
                         "explicit checkpoint permits one model handoff")


if __name__ == "__main__":
    unittest.main()
