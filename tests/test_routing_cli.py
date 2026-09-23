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

    def test_the_lifecycle_refuses_a_handoff_the_verdict_does_not_support(self):
        """assess -> handoff-check, end to end. Without a verdict the profile is
        unverified, and exit code 3 is the refusal the host must act on."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "after.py").write_text("x = 2\n")
            profile_path, session_path = root / "profile.json", root / "session.json"
            output = io.StringIO()
            with redirect_stdout(output):
                main(["assess-routing", "--path", "src/widget.py",
                      "--after", str(root / "after.py"), "--root", directory])
            profile = json.loads(output.getvalue())
            profile_path.write_text(json.dumps(profile))
            session_path.write_text(json.dumps({
                "routing_session_version": 1, "task_id": "cli", "switch_count": 0,
                "profile_id": profile["profile_id"], "selected_model": "small",
            }))
            refused = io.StringIO()
            with redirect_stdout(refused):
                code = main(["handoff-check", "--profile", str(profile_path),
                             "--session", str(session_path), "--root", directory,
                             "--event", "verification_failed"])
        self.assertEqual(code, 3)
        self.assertFalse(json.loads(refused.getvalue())["allowed"])
        self.assertIn("unverified", json.loads(refused.getvalue())["reason"])

    def test_a_profile_edited_to_widen_its_own_budget_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "after.py").write_text("x = 2\n")
            output = io.StringIO()
            with redirect_stdout(output):
                main(["assess-routing", "--path", "src/widget.py",
                      "--after", str(root / "after.py"), "--root", directory])
            profile = json.loads(output.getvalue())
            profile["handoff"]["max_model_switches"] = 99
            profile_path, session_path = root / "profile.json", root / "session.json"
            profile_path.write_text(json.dumps(profile))
            session_path.write_text(json.dumps({
                "routing_session_version": 1, "task_id": "cli", "switch_count": 0,
                "profile_id": profile["profile_id"],
            }))
            with self.assertRaises(ValueError):
                main(["handoff-check", "--profile", str(profile_path),
                      "--session", str(session_path), "--root", directory,
                      "--event", "verification_failed"])

    def test_assess_routing_profiles_a_whole_diff(self):
        """A task usually spans files; --diff is how a host profiles the set."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.py").write_text("x = 2\n")
            (root / "b.py").write_text("y = 2\n")
            diff = root / "change.diff"
            diff.write_text(
                "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n"
                "@@ -1 +1 @@\n-x = 1\n+x = 2\n"
                "diff --git a/b.py b/b.py\n--- a/b.py\n+++ b/b.py\n"
                "@@ -1 +1 @@\n-y = 1\n+y = 2\n")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["assess-routing", "--diff", str(diff), "--root", directory])
        self.assertEqual(code, EXIT_OK)
        profile = json.loads(output.getvalue())
        self.assertEqual(profile["change"]["files"], 2)
        self.assertEqual(profile["coverage"]["analysed_paths"], ["a.py", "b.py"])

    def test_assess_routing_needs_either_a_diff_or_a_path(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["assess-routing"])
        self.assertEqual(code, 2)

    def test_routing_stats_reports_only_local_aggregate_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["routing-stats", "--root", directory])
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(json.loads(output.getvalue())["events"], 0)


if __name__ == "__main__":
    unittest.main()
