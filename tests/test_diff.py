"""Stage 6 gate: diffs parse, and the before-state is rebuilt exactly or refused."""

import unittest

from yieldpoint.core.diff import PatchError, parse, reverse_apply

MODIFY = """diff --git a/tests/test_invoice.py b/tests/test_invoice.py
index 1111111..2222222 100644
--- a/tests/test_invoice.py
+++ b/tests/test_invoice.py
@@ -1,4 +1,4 @@
 def test_total():
     inv = build()
-    assert inv.total == 42
+    assert inv.total is not None
     assert inv.currency == "USD"
"""

AFTER = (
    'def test_total():\n    inv = build()\n'
    '    assert inv.total is not None\n    assert inv.currency == "USD"\n'
)
BEFORE = (
    'def test_total():\n    inv = build()\n'
    '    assert inv.total == 42\n    assert inv.currency == "USD"\n'
)


class TestParsing(unittest.TestCase):
    def test_modified_file(self):
        changes = parse(MODIFY)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].path, "tests/test_invoice.py")
        self.assertFalse(changes[0].added or changes[0].deleted)
        self.assertEqual(len(changes[0].hunks), 1)

    def test_added_file(self):
        text = (
            "diff --git a/new.py b/new.py\nnew file mode 100644\n"
            "--- /dev/null\n+++ b/new.py\n@@ -0,0 +1,2 @@\n+def test_x():\n+    assert a == 1\n"
        )
        change = parse(text)[0]
        self.assertTrue(change.added)
        self.assertIsNone(change.old_path)

    def test_deleted_file(self):
        text = (
            "diff --git a/old.py b/old.py\ndeleted file mode 100644\n"
            "--- a/old.py\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-def test_x():\n-    assert a == 1\n"
        )
        change = parse(text)[0]
        self.assertTrue(change.deleted)
        self.assertIsNone(change.new_path)

    def test_rename_is_detected(self):
        text = (
            "diff --git a/old.py b/new.py\nsimilarity index 90%\n"
            "--- a/old.py\n+++ b/new.py\n@@ -1 +1 @@\n-a = 1\n+a = 2\n"
        )
        self.assertTrue(parse(text)[0].renamed)

    def test_binary_file_is_flagged(self):
        text = (
            "diff --git a/img.png b/img.png\n"
            "Binary files a/img.png and b/img.png differ\n"
        )
        self.assertTrue(parse(text)[0].binary)

    def test_multiple_files(self):
        self.assertEqual(len(parse(MODIFY + MODIFY.replace("invoice", "other"))), 2)

    def test_empty_diff(self):
        self.assertEqual(parse(""), ())

    def test_non_diff_text_yields_nothing(self):
        self.assertEqual(parse("just some prose\nwith lines\n"), ())

    def test_multiple_hunks(self):
        text = (
            "--- a/x.py\n+++ b/x.py\n"
            "@@ -1,1 +1,1 @@\n-a = 1\n+a = 2\n"
            "@@ -10,1 +10,1 @@\n-b = 1\n+b = 2\n"
        )
        self.assertEqual(len(parse(text)[0].hunks), 2)


class TestReverseApply(unittest.TestCase):
    def test_rebuilds_the_before_state_exactly(self):
        self.assertEqual(reverse_apply(AFTER, parse(MODIFY)[0].hunks), BEFORE)

    def test_added_file_rebuilds_to_nothing(self):
        text = "--- /dev/null\n+++ b/new.py\n@@ -0,0 +1,2 @@\n+def test_x():\n+    assert a == 1\n"
        rebuilt = reverse_apply("def test_x():\n    assert a == 1\n", parse(text)[0].hunks)
        self.assertEqual(rebuilt, "")

    def test_deleted_file_rebuilds_the_whole_original(self):
        text = "--- a/old.py\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-def test_x():\n-    assert a == 1\n"
        self.assertEqual(reverse_apply("", parse(text)[0].hunks), "def test_x():\n    assert a == 1")

    def test_content_outside_hunks_is_preserved(self):
        text = "--- a/x.py\n+++ b/x.py\n@@ -2,1 +2,1 @@\n-b = 1\n+b = 2\n"
        self.assertEqual(reverse_apply("a = 0\nb = 2\nc = 3\n", parse(text)[0].hunks),
                         "a = 0\nb = 1\nc = 3\n")

    def test_no_hunks_is_the_identity(self):
        self.assertEqual(reverse_apply(AFTER, ()), AFTER)

    def test_mismatched_content_is_refused(self):
        """A silently wrong reconstruction would produce a confident wrong verdict."""
        with self.assertRaises(PatchError):
            reverse_apply("completely different\n", parse(MODIFY)[0].hunks)

    def test_hunk_past_end_of_file_is_refused(self):
        text = "--- a/x.py\n+++ b/x.py\n@@ -50,1 +50,1 @@\n-a = 1\n+a = 2\n"
        with self.assertRaises(PatchError):
            reverse_apply("a = 2\n", parse(text)[0].hunks)


if __name__ == "__main__":
    unittest.main()
