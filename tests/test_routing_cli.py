"""CLI contract for provider-neutral routing commands."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from yieldpoint.cli import EXIT_OK, main


class TestRoutingCommands(unittest.TestCase):
    def test_assess_routing_emits_a_versioned_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before, after = root / "before.py", root / "after.py"
            before.write_text("x = 1\n")
            after.write_text("x = 2\n")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main([
                    "assess-routing", "--path", "src/widget.py",
                    "--before", str(before), "--after", str(after),
                ])
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(json.loads(output.getvalue())["schema_version"], 1)


if __name__ == "__main__":
    unittest.main()
