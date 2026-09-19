"""Change-set verification: subjects pool across files so moves are not losses."""

import os
import tempfile
import unittest
from pathlib import Path

from yieldpoint.core.policy import Policy

# These fixtures are diff hunks whose line numbers must match the files on disk,
# so they omit imports. Refactor rules are scoped out; test_refactor.py covers them.
STRUCTURE_OFF = {"refactor": {"dangling_reference": "off", "export_removed": "off"}}
from yieldpoint.core.verdict import Status
from yieldpoint.verify import verify_diff

WEAKEN = """diff --git a/tests/test_invoice.py b/tests/test_invoice.py
--- a/tests/test_invoice.py
+++ b/tests/test_invoice.py
@@ -1,2 +1,2 @@
 def test_total():
-    assert inv.total == 42
+    assert inv.total is not None
"""

MOVE = """diff --git a/tests/test_invoice.py b/tests/test_invoice.py
--- a/tests/test_invoice.py
+++ b/tests/test_invoice.py
@@ -1,2 +1,2 @@
-def test_total():
-    assert inv.total == 42
+def test_currency():
+    assert inv.currency == "USD"
diff --git a/tests/test_totals.py b/tests/test_totals.py
--- /dev/null
+++ b/tests/test_totals.py
@@ -0,0 +1,2 @@
+def test_total():
+    assert inv.total == 42
"""


class DiffCase(unittest.TestCase):
    def setUp(self):
        self._previous = Path.cwd()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "tests").mkdir()
        os.chdir(self.root)

    def tearDown(self):
        os.chdir(self._previous)
        from yieldpoint.core import parsecache
        parsecache.close()
        self._tmp.cleanup()

    def write(self, rel: str, text: str):
        (self.root / rel).write_text(text, encoding="utf-8")


class TestChangeSet(DiffCase):
    def test_weakening_is_reported(self):
        self.write("tests/test_invoice.py",
                   "def test_total():\n    assert inv.total is not None\n")
        verdict = verify_diff(WEAKEN, root=self.root, policy=Policy.from_dict(STRUCTURE_OFF))
        self.assertIs(verdict.status, Status.REPAIR)
        self.assertEqual(verdict.findings[0].file, "tests/test_invoice.py")

    def test_moving_a_test_between_files_is_not_a_loss(self):
        self.write("tests/test_invoice.py",
                   'def test_currency():\n    assert inv.currency == "USD"\n')
        self.write("tests/test_totals.py",
                   "def test_total():\n    assert inv.total == 42\n")
        verdict = verify_diff(MOVE, root=self.root, policy=Policy.from_dict(STRUCTURE_OFF))
        self.assertIs(verdict.status, Status.PASS)
        self.assertEqual(len(verdict.checked), 2)

    def test_empty_diff_passes(self):
        self.assertIs(verify_diff("", root=self.root, policy=Policy.from_dict(STRUCTURE_OFF)).status, Status.PASS)


class TestUnreadableChanges(DiffCase):
    """A change we could not reconstruct is skipped, never counted as passing."""

    def test_missing_after_state_is_skipped(self):
        verdict = verify_diff(WEAKEN, root=self.root, policy=Policy.from_dict(STRUCTURE_OFF))
        self.assertEqual(verdict.checked, ())
        self.assertIn("cannot read the after-state", verdict.skipped[0])

    def test_mismatched_diff_is_skipped(self):
        self.write("tests/test_invoice.py", "something else entirely\n")
        verdict = verify_diff(WEAKEN, root=self.root, policy=Policy.from_dict(STRUCTURE_OFF))
        self.assertEqual(verdict.checked, ())
        self.assertIn("does not match", verdict.skipped[0])

    def test_binary_file_is_skipped(self):
        text = "diff --git a/i.png b/i.png\nBinary files a/i.png and b/i.png differ\n"
        self.assertIn("binary", verify_diff(text, root=self.root, policy=Policy.from_dict(STRUCTURE_OFF)).skipped[0])

    def test_custom_reader_is_used_instead_of_disk(self):
        verdict = verify_diff(
            WEAKEN, root=self.root, policy=Policy.from_dict(STRUCTURE_OFF),
            read=lambda rel: "def test_total():\n    assert inv.total is not None\n",
        )
        self.assertIs(verdict.status, Status.REPAIR)


if __name__ == "__main__":
    unittest.main()
