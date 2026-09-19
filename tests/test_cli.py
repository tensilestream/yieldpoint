"""The CLI is the cross-language API: exit codes and JSON shape are the contract."""

import io
import json
import os
import tempfile
import unittest

from yieldpoint.core.verdict import SCHEMA_VERSION
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from yieldpoint.mcp.clients import command_line
from yieldpoint.cli import EXIT_UNVERIFIED, EXIT_ERROR, EXIT_FINDINGS, EXIT_OK, main

BEFORE = 'def test_total():\n    assert inv.total == 42\n'
WEAKER = 'def test_total():\n    assert inv.total is not None\n'


def run(argv, stdin_text=None):
    out, err = io.StringIO(), io.StringIO()
    import sys

    previous = sys.stdin
    if stdin_text is not None:
        sys.stdin = io.StringIO(stdin_text)
    try:
        with redirect_stdout(out), redirect_stderr(err):
            code = main(argv)
    finally:
        sys.stdin = previous
    return code, out.getvalue(), err.getvalue()


class CliCase(unittest.TestCase):
    def setUp(self):
        self._previous = Path.cwd()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "before.py").write_text(BEFORE)
        (self.root / "weaker.py").write_text(WEAKER)
        os.chdir(self.root)

    def tearDown(self):
        os.chdir(self._previous)
        self._tmp.cleanup()


class TestCheck(CliCase):
    def test_findings_exit_one(self):
        code, out, _ = run(
            ["check", "--path", "tests/t.py", "--before", "before.py", "--after", "weaker.py"])
        self.assertEqual(code, EXIT_FINDINGS)
        self.assertIn("assertion_monotonicity", out)

    def test_clean_exits_zero(self):
        code, out, _ = run(
            ["check", "--path", "tests/t.py", "--before", "before.py", "--after", "before.py"])
        self.assertEqual(code, EXIT_OK)
        self.assertIn("ok", out)

    def test_json_emits_the_versioned_schema(self):
        _, out, _ = run(
            ["check", "--path", "tests/t.py", "--before", "before.py",
             "--after", "weaker.py", "--json"])
        payload = json.loads(out)
        self.assertEqual(payload["schema_version"], SCHEMA_VERSION)
        self.assertEqual(payload["status"], "repair")
        self.assertEqual(payload["findings"][0]["rule"], "assertion_monotonicity")

    def test_stdin_source(self):
        code, _, _ = run(
            ["check", "--path", "tests/t.py", "--before", "before.py", "--after", "-"],
            stdin_text=WEAKER)
        self.assertEqual(code, EXIT_FINDINGS)

    def test_missing_input_is_a_usage_error(self):
        self.assertEqual(run(["check", "--path", "tests/t.py"])[0], EXIT_ERROR)

    def test_missing_file_is_an_error_not_a_crash(self):
        code, _, err = run(
            ["check", "--path", "tests/t.py", "--before", "absent.py", "--after", "weaker.py"])
        self.assertEqual(code, EXIT_ERROR)
        self.assertIn("yieldpoint:", err)

    def test_skipped_files_are_reported_on_stderr(self):
        code, _, err = run(
            ["check", "--path", "tests/t.ts", "--before", "before.py", "--after", "weaker.py"])
        self.assertEqual(code, EXIT_UNVERIFIED)
        self.assertIn("skipped:", err)

    def test_unverified_exits_distinctly_from_findings(self):
        """CI must be able to tell "I found a problem" from "I checked nothing"."""
        self.assertNotEqual(EXIT_UNVERIFIED, EXIT_FINDINGS)
        self.assertNotEqual(EXIT_UNVERIFIED, EXIT_OK)


class TestHookCommand(CliCase):
    def payload(self, old, new):
        target = self.root / "tests" / "test_x.py"
        target.parent.mkdir(exist_ok=True)
        target.write_text(BEFORE)
        return json.dumps({"tool_name": "Edit", "tool_input": {
            "file_path": str(target), "old_string": old, "new_string": new}})

    def test_weakening_edit_exits_two_with_reason_on_stderr(self):
        code, _, err = run(["hook"], stdin_text=self.payload("== 42", "is not None"))
        self.assertEqual(code, EXIT_ERROR)
        self.assertIn("Yieldpoint blocked", err)

    def test_clean_edit_exits_zero_silently(self):
        code, _, err = run(["hook"], stdin_text=self.payload("== 42", "== 43"))
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(err, "")

    def test_advisory_mode_reports_but_never_denies(self):
        code, _, err = run(["hook", "--advisory"], stdin_text=self.payload("== 42", "is not None"))
        self.assertEqual(code, EXIT_OK)
        self.assertIn("Yieldpoint blocked", err)

    def test_json_decision_mode_always_exits_zero(self):
        code, out, _ = run(
            ["hook", "--json-decision"], stdin_text=self.payload("== 42", "is not None"))
        self.assertEqual(code, EXIT_OK)
        decision = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(decision["permissionDecision"], "deny")
        self.assertIn("inv.total", decision["permissionDecisionReason"])

    def test_garbage_stdin_allows(self):
        self.assertEqual(run(["hook"], stdin_text="}{")[0], EXIT_OK)


class TestInstallHook(CliCase):
    def test_creates_settings_with_the_hook(self):
        code, out, _ = run(["install-hook"])
        self.assertEqual(code, EXIT_OK)
        settings = json.loads((self.root / ".claude/settings.json").read_text())
        entry = settings["hooks"]["PreToolUse"][0]
        self.assertEqual(entry["matcher"], "Edit|MultiEdit|Write")
        self.assertEqual(entry["hooks"][0]["command"], command_line("hook"))
        self.assertTrue(
            entry["hooks"][0]["command"].endswith("hook"),
            "the registered command must invoke the hook subcommand",
        )
        self.assertIn("registered", out)

    def test_preserves_existing_settings_and_backs_them_up(self):
        path = self.root / ".claude/settings.json"
        path.parent.mkdir()
        path.write_text(json.dumps({"model": "opus", "hooks": {"PreToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "other"}]}]}}))

        run(["install-hook"])
        settings = json.loads(path.read_text())
        self.assertEqual(settings["model"], "opus")
        self.assertEqual(len(settings["hooks"]["PreToolUse"]), 2)
        self.assertTrue(path.with_suffix(".json.yieldpoint-backup").is_file())

    def test_reinstalling_does_not_duplicate_the_entry(self):
        run(["install-hook"])
        run(["install-hook"])
        settings = json.loads((self.root / ".claude/settings.json").read_text())
        self.assertEqual(len(settings["hooks"]["PreToolUse"]), 1)

    def test_advisory_install_records_the_flag(self):
        run(["install-hook", "--advisory"])
        settings = json.loads((self.root / ".claude/settings.json").read_text())
        self.assertIn("--advisory", settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"])


if __name__ == "__main__":
    unittest.main()


class TestInit(CliCase):
    """``init`` is the one-command setup, so it must be safe to run twice."""

    def _repo(self):
        root = self.root / "proj"
        root.mkdir(exist_ok=True)
        return root

    def test_it_writes_config_mcp_and_hook(self):
        root = self._repo()
        code, out, _ = run(["init", "--root", str(root)])
        self.assertEqual(code, EXIT_OK)
        self.assertTrue((root / ".yieldpoint.json").is_file())
        self.assertTrue((root / ".mcp.json").is_file())
        self.assertTrue((root / ".claude" / "settings.json").is_file())
        self.assertIn("advisory", out)

    def test_the_hook_is_advisory_unless_enforce_is_given(self):
        root = self._repo()
        run(["init", "--root", str(root)])
        settings = json.loads((root / ".claude" / "settings.json").read_text())
        command = settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        self.assertIn("--advisory", command)

    def test_enforce_removes_advisory(self):
        root = self._repo()
        run(["init", "--root", str(root), "--enforce"])
        settings = json.loads((root / ".claude" / "settings.json").read_text())
        command = settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        self.assertNotIn("--advisory", command)

    def test_an_existing_config_is_not_overwritten(self):
        root = self._repo()
        (root / ".yieldpoint.json").write_text('{"version": 1, "project": "mine"}')
        run(["init", "--root", str(root)])
        self.assertIn("mine", (root / ".yieldpoint.json").read_text())

    def test_running_it_twice_does_not_duplicate_the_hook(self):
        root = self._repo()
        run(["init", "--root", str(root)])
        run(["init", "--root", str(root)])
        settings = json.loads((root / ".claude" / "settings.json").read_text())
        entries = settings["hooks"]["PreToolUse"]
        self.assertEqual(len(entries), 1, "init must be idempotent")

    def test_no_hook_skips_enforcement(self):
        root = self._repo()
        code, out, _ = run(["init", "--root", str(root), "--no-hook"])
        self.assertEqual(code, EXIT_OK)
        self.assertFalse((root / ".claude" / "settings.json").exists())
        self.assertIn("only explain", out)


class TestTurnEndReport(CliCase):
    """One file, refreshed in place at the end of every turn.

    Writing a fresh page per run would accumulate untracked files in somebody's
    repository; writing to the repository root would put one there at all. So
    the default lands in the state directory, which ignores itself.
    """

    def _repo(self):
        root = self.root / "proj"
        root.mkdir(exist_ok=True)
        return root

    def test_init_registers_a_stop_hook_that_refreshes_the_report(self):
        root = self._repo()
        run(["init", "--root", str(root)])
        settings = json.loads((root / ".claude" / "settings.json").read_text())
        commands = [
            h["command"]
            for entry in settings["hooks"]["Stop"] for h in entry["hooks"]
        ]
        self.assertTrue(any("report" in c for c in commands))

    def test_it_can_be_declined(self):
        root = self._repo()
        run(["init", "--root", str(root), "--no-report"])
        settings = json.loads((root / ".claude" / "settings.json").read_text())
        self.assertNotIn("Stop", settings["hooks"])

    def test_running_init_twice_does_not_duplicate_the_stop_hook(self):
        root = self._repo()
        run(["init", "--root", str(root)])
        run(["init", "--root", str(root)])
        settings = json.loads((root / ".claude" / "settings.json").read_text())
        self.assertEqual(len(settings["hooks"]["Stop"]), 1)

    def test_the_report_defaults_into_the_ignored_state_directory(self):
        root = self._repo()
        (root / ".yieldpoint.json").write_text("{}")
        (root / "a.py").write_text("x = 1\n")
        code, out, _ = run(["report", "--root", str(root)])
        self.assertEqual(code, EXIT_OK)
        self.assertTrue((root / ".yieldpoint" / "report.html").is_file())
        self.assertFalse(
            list(root.glob("*.html")),
            "nothing may be written to the repository root",
        )
