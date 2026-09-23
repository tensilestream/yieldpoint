from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UPDATER = ROOT / "scripts" / "update_homebrew_formula.py"
FORMULA = ROOT / "Formula" / "yieldpoint.rb"


class TestHomebrewFormulaUpdater(unittest.TestCase):
    def test_updates_an_explicit_tap_formula_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "yieldpoint.rb"
            target.write_text(FORMULA.read_text(encoding="utf-8"), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(UPDATER), "0.1.5", "a" * 64, "--formula", str(target)],
                text=True, capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            updated = target.read_text(encoding="utf-8")
            self.assertIn("tags/v0.1.5.tar.gz", updated)
            self.assertIn(f'sha256 "{"a" * 64}"', updated)
            self.assertIn("tags/v0.1.4.tar.gz", FORMULA.read_text(encoding="utf-8"))

    def test_refuses_invalid_digest(self) -> None:
        result = subprocess.run(
            [sys.executable, str(UPDATER), "0.1.5", "bad"], text=True, capture_output=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("sha256", result.stderr)
