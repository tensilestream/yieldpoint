"""Every surface reports the same findings for the same change.

From the field review: *"If the AI agent sees a different rule set than the
human's CI, trust evaporates."* That is correct, and it is the kind of promise
a README cannot keep. A surface drifts by accident — a flag that filters, a
default that differs, a path that skips a rule — and nothing notices until
somebody is arguing with their own pipeline.

So it is a test. One repository, one policy, one change, through every door.
"""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.test_cli import run

POLICY = {"structure": {"max_file_lines": 300, "max_lines": 50}}

#: Two findings by construction: a file that was already too long and grew, and
#: a handler this change added that catches everything and says nothing.
BEFORE = ("def go():\n    return 1\n\n\n"
          + "\n".join(f"x{i} = 1" for i in range(400)) + "\n")
AFTER = BEFORE + (
    "\n\ndef risky():\n    try:\n        go()\n    except Exception:\n        pass\n")


def _git(args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, check=False)


def _repo():
    root = Path(tempfile.mkdtemp())
    _git(["init", "-q", "-b", "main", "."], root)
    _git(["config", "user.email", "t@t"], root)
    _git(["config", "user.name", "T"], root)
    (root / ".yieldpoint.json").write_text(json.dumps(POLICY))
    (root / "big.py").write_text(BEFORE)
    _git(["add", "-A"], root)
    _git(["commit", "-qm", "base"], root)
    (root / "big.py").write_text(AFTER)
    return root


def _key(rule, file, line):
    return (rule, file, line)


class TestEverySurfaceAgrees(unittest.TestCase):
    """The finding set, not the wording, must be identical everywhere."""

    @classmethod
    def setUpClass(cls):
        cls.root = _repo()
        cls.policy = str(cls.root / ".yieldpoint.json")

    def _expected(self):
        """The library answer, which every surface is a rendering of."""
        from yieldpoint.verify import verify_diff
        from yieldpoint.worktree import uncommitted

        diff = uncommitted(self.root)
        verdict = verify_diff(diff.text, root=str(self.root), policy=self.policy)
        return {_key(f.rule, f.file, f.line) for f in verdict.findings}

    def test_the_fixture_actually_produces_findings(self):
        """A test that compares empty sets agrees with everything."""
        found = self._expected()
        self.assertEqual({r for r, _, _ in found},
                         {"file_too_long", "swallowed_exception"})

    def test_the_cli_agrees_with_the_library(self):
        _, out, _ = run(["review", "--root", str(self.root),
                         "--policy", self.policy, "--json"])
        payload = json.loads(out)
        self.assertEqual(
            {_key(f["rule"], f["file"], f["line"]) for f in payload["findings"]},
            self._expected())

    def test_sarif_agrees_with_the_library(self):
        _, out, _ = run(["review", "--root", str(self.root),
                         "--policy", self.policy, "--sarif"])
        results = json.loads(out)["runs"][0]["results"]
        self.assertEqual(
            {_key(r["ruleId"],
                  r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"],
                  r["locations"][0]["physicalLocation"]["region"]["startLine"])
             for r in results},
            self._expected())

    def test_the_markdown_summary_names_every_finding(self):
        _, out, _ = run(["summary", "--root", str(self.root), "--policy", self.policy])
        for rule, file, _line in self._expected():
            self.assertIn(rule, out)
            self.assertIn(file, out)

    def test_the_stop_hook_agrees_with_the_library(self):
        from yieldpoint import stop

        outcome = stop.evaluate(str(self.root), self.policy)
        self.assertEqual(
            {_key(f.rule, f.file, f.line) for f in outcome.verdict.findings},
            self._expected())

    def test_the_mcp_server_agrees_with_the_library(self):
        from yieldpoint.core.policy import Policy
        from yieldpoint.mcp.tools import call

        text, _meta, _err = call("yieldpoint_review", {"root": str(self.root)},
                                 Policy.load(self.policy))
        for rule, file, _line in self._expected():
            self.assertIn(rule, text)
            self.assertIn(file, text)


class TestAcknowledgementsAreHonouredEverywhere(unittest.TestCase):
    """An acknowledgement that works in the editor and not in CI is worse than none."""

    @classmethod
    def setUpClass(cls):
        cls.root = _repo()
        cls.policy = str(cls.root / ".yieldpoint.json")
        # Directly above the handler, not above the `try`: the finding points
        # at the `except` line and an acknowledgement reaches two lines back.
        (cls.root / "big.py").write_text(AFTER.replace(
            "    except Exception:",
            "    # yieldpoint: allow swallowed_exception - deliberate, see issue 12\n"
            "    except Exception:"))

    def _rules(self, argv):
        _, out, _ = run(argv)
        return out

    def test_the_cli_honours_it(self):
        out = self._rules(["review", "--root", str(self.root),
                           "--policy", self.policy, "--json"])
        self.assertNotIn("swallowed_exception", json.dumps(json.loads(out)["findings"]))

    def test_sarif_honours_it(self):
        out = self._rules(["review", "--root", str(self.root),
                           "--policy", self.policy, "--sarif"])
        rules = {r["ruleId"] for r in json.loads(out)["runs"][0]["results"]}
        self.assertNotIn("swallowed_exception", rules)

    def test_the_stop_hook_honours_it(self):
        from yieldpoint import stop

        outcome = stop.evaluate(str(self.root), self.policy)
        self.assertNotIn("swallowed_exception",
                         {f.rule for f in outcome.verdict.findings})

    def test_the_other_finding_is_still_reported(self):
        """An acknowledgement names one rule. It is not an off switch."""
        out = self._rules(["review", "--root", str(self.root),
                           "--policy", self.policy, "--json"])
        self.assertIn("file_too_long",
                      {f["rule"] for f in json.loads(out)["findings"]})


if __name__ == "__main__":
    unittest.main()
