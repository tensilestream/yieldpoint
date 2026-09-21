"""Where a new file was put, given the tree it was put into.

A failure mode a field review named as characteristic of agent-written code:
a new `foo_bar.py` dropped beside an existing `foo/` package, because the thing
writing it can see the file and not the directory.
"""

import tempfile
import unittest
from pathlib import Path

from yieldpoint.core.layout import SIBLING_MODULE, check
from yieldpoint.core.verdict import Confidence, Status


class TestSiblingModule(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        for package in ("pkg/core", "pkg/core_deep"):
            (self.root / package).mkdir(parents=True)
            (self.root / package / "__init__.py").touch()
        (self.root / "pkg" / "notapackage").mkdir()

    def _check(self, *paths):
        return check(list(paths), self.root, Status.REPAIR)

    def test_a_new_module_named_for_a_package_beside_it_is_reported(self):
        found = self._check("pkg/core_reader.py")
        self.assertEqual([f.rule for f in found], [SIBLING_MODULE])
        self.assertIn("pkg/core/reader.py", found[0].prescription)

    def test_the_longest_matching_package_wins(self):
        """With both `core/` and `core_deep/`, the more specific one owns it."""
        found = self._check("pkg/core_deep_reader.py")
        self.assertIn("pkg/core_deep/reader.py", found[0].prescription)

    def test_a_directory_without_an_init_is_not_a_package(self):
        self.assertEqual(self._check("pkg/notapackage_thing.py"), [])

    def test_a_name_matching_no_package_is_left_alone(self):
        self.assertEqual(self._check("pkg/unrelated_thing.py"), [])

    def test_a_module_with_no_underscore_cannot_shadow_anything(self):
        self.assertEqual(self._check("pkg/core.py"), [])

    def test_only_python_files_are_considered(self):
        self.assertEqual(self._check("pkg/core_reader.txt"), [])

    def test_the_finding_is_exact_because_the_filesystem_is_not_a_guess(self):
        self.assertIs(self._check("pkg/core_reader.py")[0].confidence, Confidence.EXACT)

    def test_a_privately_named_module_is_not_a_package_prefix(self):
        """A leading underscore is a visibility convention. Without this the
        empty prefix resolves to the parent's own `__init__.py` and every
        `_private.py` in any package is reported."""
        (self.root / "pkg" / "__init__.py").touch()
        self.assertEqual(self._check("pkg/_private.py"), [])

    def test_a_package_marker_is_not_reported_against_its_own_package(self):
        (self.root / "pkg" / "__init__.py").touch()
        self.assertEqual(self._check("pkg/__init__.py"), [])

    def test_a_trailing_underscore_names_no_module(self):
        self.assertEqual(self._check("pkg/core_.py"), [])

    def test_switching_the_severity_off_switches_the_rule_off(self):
        self.assertEqual(check(["pkg/core_reader.py"], self.root, None), [])


class TestOnlyNewFiles(unittest.TestCase):
    """A repository that already has such a pair decided that at some point."""

    def _rules_for(self, diff_text):
        from yieldpoint.verify import verify_diff

        root = Path(tempfile.mkdtemp())
        (root / "core").mkdir()
        (root / "core" / "__init__.py").touch()
        (root / "core_reader.py").write_text("x = 1\n")
        return [f.rule for f in verify_diff(diff_text, root=str(root)).findings]

    def test_an_existing_pair_is_not_re_litigated(self):
        edited = self._rules_for(
            "--- a/core_reader.py\n+++ b/core_reader.py\n"
            "@@ -1 +1 @@\n-x = 1\n+x = 2\n")
        self.assertNotIn(SIBLING_MODULE, edited)

    def test_a_newly_added_one_is(self):
        added = self._rules_for(
            "--- /dev/null\n+++ b/core_reader.py\n@@ -0,0 +1 @@\n+x = 1\n")
        self.assertIn(SIBLING_MODULE, added)


class TestItDoesNotBlock(unittest.TestCase):
    def test_it_is_reported_as_shape_rather_than_a_weakening(self):
        from yieldpoint.core.structure import MAINTAINABILITY_RULES

        self.assertIn(SIBLING_MODULE, MAINTAINABILITY_RULES)


if __name__ == "__main__":
    unittest.main()
