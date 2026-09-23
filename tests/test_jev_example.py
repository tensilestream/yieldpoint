"""Optional Jev examples must remain useful without credentials or network."""

from __future__ import annotations

import json
import os
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


if __name__ == "__main__":
    unittest.main()
