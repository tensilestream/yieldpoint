"""``yieldpoint review`` and ``yieldpoint_review``: the zero-argument entry point.

The value of this surface is entirely that it takes no arguments, so the things
worth pinning are the ways it can be called wrongly and must not blow up.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from yieldpoint.worktree import uncommitted


def _git(args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                          text=True, timeout=60, check=False)


class TestOutsideARepository(unittest.TestCase):
    def test_it_explains_instead_of_raising(self):
        with tempfile.TemporaryDirectory() as tmp:
            diff = uncommitted(tmp)
        self.assertFalse(diff.ok)
        self.assertIn("not inside a git repository", diff.reason)


class TestInARepository(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        _git(["init", "-q", "."], self.tmp.name)
        _git(["config", "user.email", "t@example.com"], self.tmp.name)
        _git(["config", "user.name", "t"], self.tmp.name)
        (self.root / "test_a.py").write_text("def test_x():\n    assert total == 42\n")
        _git(["add", "-A"], self.tmp.name)
        _git(["commit", "-qm", "initial"], self.tmp.name)

    def tearDown(self):
        from yieldpoint.core import parsecache
        parsecache.close()
        self.tmp.cleanup()

    def test_a_clean_tree_says_so_rather_than_failing(self):
        diff = uncommitted(self.root)
        self.assertFalse(diff.ok)
        self.assertIn("no uncommitted changes", diff.reason)

    def test_it_finds_a_weakened_assertion(self):
        (self.root / "test_a.py").write_text("def test_x():\n    assert total\n")
        diff = uncommitted(self.root)
        self.assertTrue(diff.ok)
        self.assertIn("-    assert total == 42", diff.text)

    def test_untracked_files_are_included(self):
        """A newly written test is the most interesting thing an agent produces."""
        (self.root / "test_new.py").write_text("def test_y():\n    assert b == 1\n")
        diff = uncommitted(self.root)
        self.assertTrue(diff.ok)
        self.assertIn("test_new.py", diff.text)

    def test_staged_only_ignores_unstaged_work(self):
        (self.root / "test_a.py").write_text("def test_x():\n    assert total\n")
        self.assertFalse(uncommitted(self.root, staged=True).ok)
        _git(["add", "-A"], self.tmp.name)
        self.assertTrue(uncommitted(self.root, staged=True).ok)

    def test_the_cli_reports_the_weakening(self):
        (self.root / "test_a.py").write_text("def test_x():\n    assert total\n")
        completed = subprocess.run(
            [sys.executable, "-m", "yieldpoint", "review", "--root", str(self.root)],
            capture_output=True, text=True, timeout=120,
            cwd=str(Path(__file__).resolve().parent.parent),
        )
        self.assertIn("assertion_monotonicity", completed.stdout)
        self.assertNotEqual(completed.returncode, 0)


if __name__ == "__main__":
    unittest.main()
