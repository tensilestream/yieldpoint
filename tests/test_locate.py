"""One repository, one place for state.

Without a shared answer to "which repository is this?", each command stores its
state wherever it was pointed, and a project accumulates several ``.yieldpoint``
directories holding partial views of the same work. That is how `scan yieldpoint`
came to leave a cache inside the package it had just looked at.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from yieldpoint import ledger
from yieldpoint.core.locate import repository
from yieldpoint.core.policy import Policy


class TestRepositoryRoot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        (self.root / ".yieldpoint.json").write_text("{}")
        self.nested = self.root / "package" / "deep"
        self.nested.mkdir(parents=True)

    def tearDown(self):
        from yieldpoint.core import parsecache
        parsecache.close()
        self.tmp.cleanup()

    def test_a_subdirectory_resolves_to_the_root(self):
        self.assertEqual(repository(self.nested), self.root)

    def test_a_file_resolves_to_its_repository(self):
        module = self.nested / "module.py"
        module.write_text("x = 1\n")
        self.assertEqual(repository(module), self.root)

    def test_git_counts_when_there_is_no_config(self):
        with tempfile.TemporaryDirectory() as plain:
            root = Path(plain).resolve()
            (root / ".git").mkdir()
            inner = root / "src" / "pkg"
            inner.mkdir(parents=True)
            self.assertEqual(repository(inner), root)

    def test_a_directory_with_no_markers_is_its_own_root(self):
        """Predictable beats clever: scratch directories keep their own state."""
        with tempfile.TemporaryDirectory() as plain:
            root = Path(plain).resolve()
            self.assertEqual(repository(root), root)

    def test_the_ledger_lands_at_the_root_from_anywhere(self):
        from_root = ledger.path_for(Policy(), self.root)
        from_deep = ledger.path_for(Policy(), self.nested)
        self.assertEqual(from_root, from_deep)
        self.assertEqual(from_root.parent.parent, self.root)

    def test_scanning_a_subdirectory_leaves_no_state_inside_it(self):
        """The bug this exists to prevent."""
        from yieldpoint.scan import scan

        package = self.root / "package"
        (package / "module.py").write_text("def f():\n    return 1\n")
        scan(package, jobs=1)
        self.assertFalse(
            (package / ".yieldpoint").exists(),
            "state must not be written inside the directory being scanned",
        )


if __name__ == "__main__":
    unittest.main()
