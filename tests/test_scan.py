"""Whole-repository audit.

A scan answers a different question from a check: not "what did this change do"
but "what is the state of this repository". Rules that are differential when
verifying an edit — so that inherited debt is not blamed on the next change —
must run absolutely here, or a scan would report nothing at all.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from yieldpoint.commands import EXIT_FINDINGS, EXIT_OK
from yieldpoint.core import parsecache
from yieldpoint.core.policy import Policy
from yieldpoint.core.verdict import SCHEMA_VERSION, Status
from yieldpoint.scan import ScanResult, scan, walk
from tests.test_cli import run

LONG_MODULE = "\n".join(f"def f{i}():\n    return {i}" for i in range(200)) + "\n"


class ScanCase(unittest.TestCase):
    def setUp(self):
        self._previous = Path.cwd()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        os.chdir(self.root)

    def tearDown(self):
        os.chdir(self._previous)
        parsecache.close()
        self._tmp.cleanup()

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path


class TestWalking(unittest.TestCase):
    def test_order_is_stable_so_two_scans_agree(self):
        first = [str(p) for p in walk(Path("yieldpoint"), Policy())]
        second = [str(p) for p in walk(Path("yieldpoint"), Policy())]
        self.assertEqual(first, second)
        self.assertEqual(first, sorted(first))

    def test_only_analysable_files_are_yielded(self):
        self.assertTrue(all(str(p).endswith(".py") for p in walk(Path("yieldpoint"), Policy())))


class TestIgnoring(ScanCase):
    def test_default_ignores_exclude_build_output(self):
        self.write("src/real.py", "def f():\n    return 1\n")
        self.write("node_modules/pkg/bad.py", "def f():\n    return nope()\n")
        self.write("__pycache__/x.py", "def f():\n    return nope()\n")
        self.assertEqual(scan(self.root, Policy()).files, 1)

    def test_ignores_are_configurable(self):
        self.write("src/a.py", "x = 1\n")
        self.write("vendor/b.py", "x = 1\n")
        policy = Policy.from_dict({"scan": {"ignore": ["**/vendor/**"]}})
        self.assertEqual(scan(self.root, policy).files, 1)

    def test_oversized_files_are_skipped(self):
        self.write("src/huge.py", "x = 1\n" * 50)
        policy = Policy.from_dict({"scan": {"max_file_bytes": 10}})
        self.assertEqual(scan(self.root, policy).files, 0)

    def test_a_single_file_may_be_scanned(self):
        path = self.write("src/a.py", "x = 1\n")
        self.assertEqual(scan(path, Policy()).files, 1)


class TestAbsoluteEvaluation(ScanCase):
    """Differential rules must not go silent just because there is no before."""

    def test_structure_limits_apply_without_a_previous_state(self):
        self.write("src/big.py", LONG_MODULE)
        result = scan(self.root, Policy())
        self.assertIn("file_too_long", result.by_rule())

    def test_boundary_violations_are_reported(self):
        self.write("app/core/x.py", "import requests\n")
        policy = Policy.from_dict({"boundaries": {"zones": [
            {"name": "core", "path": "app/core/**", "forbidden_imports": ["requests"]}
        ]}})
        self.assertIn("boundary_violation", scan(self.root, policy).by_rule())

    def test_dangling_references_are_reported(self):
        self.write("src/a.py", "def f():\n    return missing_helper()\n")
        self.assertIn("dangling_reference", scan(self.root, Policy()).by_rule())

    def test_test_contract_offences_are_reported(self):
        self.write("tests/test_a.py", "def test_x():\n    assert True\n")
        self.assertIn("vacuous_assertion", scan(self.root, Policy()).by_rule())

    def test_a_clean_repository_passes(self):
        self.write("src/a.py", "def add(a, b):\n    return a + b\n")
        result = scan(self.root, Policy())
        self.assertIs(result.verdict.status, Status.PASS)
        self.assertEqual(result.by_rule(), {})


class TestResult(ScanCase):
    def test_findings_are_counted_by_rule(self):
        self.write("src/utils.py", "def f():\n    return nope()\n")
        counts = scan(self.root, Policy()).by_rule()
        self.assertEqual(counts["utility_module"], 1)
        self.assertEqual(counts["dangling_reference"], 1)

    def test_unreadable_files_are_recorded_not_counted_as_clean(self):
        path = self.write("src/bad.py", "x = 1\n")
        path.write_bytes(b"\xff\xfe\x00bad")
        result = scan(self.root, Policy())
        self.assertEqual(result.files, 0)
        self.assertEqual(len(result.unreadable), 1)

    def test_an_empty_tree_is_clean(self):
        self.assertEqual(scan(self.root, Policy()), ScanResult(verdict=scan(self.root).verdict))


class TestCommand(ScanCase):
    def test_findings_exit_one(self):
        self.write("src/a.py", "def f():\n    return missing()\n")
        code, out, _ = run(["scan", str(self.root)])
        self.assertEqual(code, EXIT_FINDINGS)
        self.assertIn("dangling_reference", out)
        self.assertIn("summary", out)

    def test_a_clean_tree_exits_zero(self):
        self.write("src/a.py", "def add(a, b):\n    return a + b\n")
        code, out, _ = run(["scan", str(self.root)])
        self.assertEqual(code, EXIT_OK)
        self.assertIn("nothing to report", out)

    def test_json_output_uses_the_versioned_schema(self):
        self.write("src/a.py", "def f():\n    return missing()\n")
        _, out, _ = run(["scan", str(self.root), "--json"])
        self.assertEqual(json.loads(out)["schema_version"], SCHEMA_VERSION)

    def test_rule_filter_narrows_the_report(self):
        self.write("src/utils.py", "def f():\n    return missing()\n")
        code, out, _ = run(["scan", str(self.root), "--rule", "utility_module"])
        self.assertEqual(code, EXIT_FINDINGS)
        self.assertIn("utility_module", out)
        self.assertNotIn("dangling_reference", out)

    def test_filtering_to_a_clean_rule_exits_zero(self):
        self.write("src/a.py", "def f():\n    return missing()\n")
        code, _, _ = run(["scan", str(self.root), "--rule", "boundary_violation"])
        self.assertEqual(code, EXIT_OK)


class TestThisRepository(unittest.TestCase):
    def test_the_real_tree_has_no_correctness_findings(self):
        """Maintainability limits are advisory here; correctness rules must be clean."""
        root = Path(__file__).resolve().parent.parent
        result = scan(root / "yieldpoint", root / ".yieldpoint.json")
        for rule in ("dangling_reference", "boundary_violation", "export_removed",
                     "duplicate_implementation", "file_too_long", "utility_module"):
            self.assertNotIn(rule, result.by_rule(), rule)


if __name__ == "__main__":
    unittest.main()
