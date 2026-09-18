"""Linter integration: opt-in, advisory, and never able to block.

Parser tests use recorded tool output so the suite does not depend on which
tools happen to be installed — the same reason linter findings are not allowed
to block a verdict.
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from aegisflow.core.linters import registry, runner
from aegisflow.core.linters.adapter import FAST, SLOW, Adapter, LintFinding
from aegisflow.core.policy import Policy
from aegisflow.core.verdict import Confidence, Finding, Status
from aegisflow.verify import verify_change


class TestParsers(unittest.TestCase):
    def test_ruff_json(self):
        recorded = """[
          {"code": "F401", "message": "`os` imported but unused",
           "location": {"row": 3, "column": 8}, "fix": {"applicability": "safe"}}
        ]"""
        found = registry.get("ruff").parse(recorded, "", 1)
        self.assertEqual(len(found), 1)
        self.assertEqual((found[0].code, found[0].line, found[0].fixable), ("F401", 3, True))

    def test_ruff_json_handles_garbage(self):
        self.assertEqual(registry.get("ruff").parse("not json", "", 1), ())

    def test_sarif(self):
        recorded = """{"runs": [{"results": [
          {"ruleId": "S101", "message": {"text": "assert used"},
           "locations": [{"physicalLocation": {"region": {"startLine": 7}}}]}
        ]}]}"""
        found = registry.get("bandit").parse(recorded, "", 0)
        self.assertEqual((found[0].code, found[0].line), ("S101", 7))

    def test_gnu_diagnostics(self):
        found = registry.get("mypy").parse("app/x.py:12:5: error: bad type\n", "", 1)
        self.assertEqual((found[0].line, found[0].column), (12, 5))
        self.assertIn("bad type", found[0].message)

    def test_gnu_ignores_unparseable_lines(self):
        self.assertEqual(registry.get("mypy").parse("Success: no issues\n", "", 0), ())

    def test_presence_reports_only_on_failure(self):
        formatter = registry.get("ruff-format")
        self.assertEqual(formatter.parse("", "", 0), ())
        self.assertEqual(len(formatter.parse("would reformat x.py", "", 1)), 1)


class TestRegistry(unittest.TestCase):
    def test_catalogue_covers_several_ecosystems(self):
        for name in ("ruff", "spotless", "eslint", "gofmt", "rustfmt", "shellcheck"):
            self.assertIsNotNone(registry.get(name), name)

    def test_adapters_are_selected_by_file_suffix(self):
        python = {a.name for a in registry.for_path("x.py", registry.names())}
        java = {a.name for a in registry.for_path("X.java", registry.names())}
        self.assertIn("ruff", python)
        self.assertNotIn("ruff", java)
        self.assertIn("spotless", java)

    def test_only_enabled_tools_are_selected(self):
        chosen = registry.for_path("x.py", ["ruff"])
        self.assertEqual([a.name for a in chosen], ["ruff"])

    def test_unknown_tool_resolves_to_none(self):
        self.assertIsNone(registry.get("not-a-real-linter"))

    def test_argv_substitutes_only_the_path(self):
        self.assertIn("/tmp/x.py", registry.get("ruff").command("/tmp/x.py"))


class TestRunnerSafety(unittest.TestCase):
    def test_missing_tool_is_skipped_not_passed(self):
        adapter = Adapter("ghost", "", (".py",), ("definitely-not-installed", "{path}"),
                          "gnu", FAST)
        result = runner.run(adapter, "x.py", "x = 1\n")
        self.assertFalse(result.ran)
        self.assertIn("not installed", result.skipped)

    def test_project_scoped_tool_cannot_verify_unwritten_content(self):
        result = runner.run(registry.get("spotless"), "A.java", "class A {}")
        self.assertFalse(result.ran)
        self.assertIn("not yet written", result.skipped)

    def test_timeout_is_reported_not_raised(self):
        adapter = Adapter(
            "sleeper", "", (".py",),
            ("python3", "-c", "import time; time.sleep(30)", "{path}"), "gnu", FAST,
        )
        result = runner.run(adapter, "x.py", "x = 1\n", timeout=1)
        self.assertFalse(result.ran)
        self.assertIn("timed out", result.skipped)

    def test_tool_failing_with_no_parseable_output_is_skipped_not_passed(self):
        adapter = Adapter(
            "broken", "", (".py",),
            ("python3", "-c", "import sys; sys.exit(3)", "{path}"), "gnu", FAST,
        )
        result = runner.run(adapter, "x.py", "x = 1\n")
        self.assertFalse(result.ran)
        self.assertIn("exited 3", result.skipped)

    def test_no_adapter_uses_a_shell(self):
        for name in registry.names():
            argv = registry.get(name).argv
            self.assertNotIn(argv[0], ("sh", "bash", "zsh", "cmd", "powershell"), name)


class TestPolicy(unittest.TestCase):
    def test_disabled_by_default(self):
        self.assertFalse(Policy().linters.enabled)
        self.assertEqual(Policy().linters.tools, ())

    def test_unknown_tool_warns_and_is_dropped(self):
        policy = Policy.from_dict({"linters": {"enabled": True, "tools": ["ruff", "bogus"]}})
        self.assertEqual(policy.linters.tools, ("ruff",))
        self.assertTrue(any("bogus" in w for w in policy.warnings))

    def test_block_severity_is_refused(self):
        """An external tool's verdict depends on its version; it may not stop work."""
        policy = Policy.from_dict({"linters": {"enabled": True, "severity": "block"}})
        self.assertIs(policy.linters.severity, Status.ESCALATE)
        self.assertTrue(any("not permitted" in w for w in policy.warnings))

    def test_severity_is_configurable(self):
        policy = Policy.from_dict({"linters": {"severity": "escalate"}})
        self.assertIs(policy.linters.severity, Status.ESCALATE)

    def test_tools_may_be_turned_off_entirely(self):
        policy = Policy.from_dict({"linters": {"enabled": True, "severity": "off"}})
        self.assertIsNone(policy.linters.severity)


class TestExternalFindingsCannotBlock(unittest.TestCase):
    def test_constructing_a_blocking_external_finding_raises(self):
        with self.assertRaises(ValueError):
            Finding(rule="lint.ruff.F401", status=Status.BLOCK, file="x.py", line=1,
                    detail="d", prescription="p", confidence=Confidence.EXTERNAL)


class TestVerifyIntegration(unittest.TestCase):
    def setUp(self):
        self._previous = Path.cwd()
        self._tmp = tempfile.TemporaryDirectory()
        import os

        os.chdir(self._tmp.name)
        Path("tests").mkdir()

    def tearDown(self):
        import os

        os.chdir(self._previous)
        self._tmp.cleanup()

    def test_linters_off_by_default_produce_nothing(self):
        verdict = verify_change(None, "import os, sys\n", "src/x.py", Policy())
        self.assertEqual(verdict.findings, ())

    def test_slow_tools_are_skipped_unless_requested(self):
        policy = Policy.from_dict({"linters": {"enabled": True, "tools": ["mypy"]}})
        verdict = verify_change(None, "x = 1\n", "src/x.py", policy)
        self.assertTrue(any("slow" in note for note in verdict.skipped))

    @unittest.skipIf(shutil.which("ruff") is None, "ruff not installed")
    def test_ruff_findings_are_external_and_advisory(self):
        policy = Policy.from_dict({"linters": {"enabled": True, "tools": ["ruff"]}})
        verdict = verify_change(None, "import os, sys\n", "src/x.py", policy)
        self.assertTrue(verdict.findings)
        for finding in verdict.findings:
            self.assertIs(finding.confidence, Confidence.EXTERNAL)
            self.assertTrue(finding.rule.startswith("lint.ruff."))
        self.assertIs(verdict.status, Status.REPAIR)

    @unittest.skipIf(shutil.which("ruff") is None, "ruff not installed")
    def test_clean_file_produces_no_lint_findings(self):
        policy = Policy.from_dict({"linters": {"enabled": True, "tools": ["ruff"]}})
        self.assertEqual(verify_change(None, "x = 1\n", "src/x.py", policy).findings, ())

    @unittest.skipIf(shutil.which("ruff") is None, "ruff not installed")
    def test_lint_and_test_contract_findings_coexist(self):
        policy = Policy.from_dict({"linters": {"enabled": True, "tools": ["ruff"]}})
        before = "def test_total():\n    assert inv.total == 42\n"
        after = "import os\ndef test_total():\n    assert inv.total is not None\n"
        rules = {f.rule for f in verify_change(before, after, "tests/test_x.py", policy).findings}
        self.assertIn("assertion_monotonicity", rules)
        self.assertTrue(any(r.startswith("lint.ruff.") for r in rules))

    def test_rule_name_does_not_repeat_the_tool(self):
        item = LintFinding(tool="ruff-format", code="ruff-format.format", message="m")
        from aegisflow.verify import _lint_rule

        self.assertEqual(_lint_rule(item), "lint.ruff-format.format")


if __name__ == "__main__":
    unittest.main()
