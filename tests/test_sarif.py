"""Findings in the one format read by people who did not install this.

A GitHub or GitLab annotation is seen by reviewers who never chose Yieldpoint,
which makes the severity mapping a claim made on their behalf. It is
deliberately conservative.
"""

import json
import unittest

from yieldpoint.core.policy import Policy, Structure
from yieldpoint.core.verdict import Confidence, Finding, Status, Verdict
from yieldpoint.sarif import (
    ERROR,
    NOTE,
    WARNING,
    advisory_rules,
    build,
    dumps,
    fingerprint,
    level_for,
)


def _finding(rule="assertion_monotonicity", status=Status.REPAIR,
             confidence=Confidence.EXACT, line=7, symbol=None):
    return Finding(rule=rule, status=status, file="src/pay.py", line=line,
                   detail="An assertion got weaker.", prescription="Restore it.",
                   confidence=confidence, symbol=symbol)


class TestSeverityIsConservative(unittest.TestCase):
    def test_a_blocking_exact_finding_is_an_error(self):
        self.assertEqual(level_for(_finding(status=Status.BLOCK)), ERROR)

    def test_an_escalating_exact_finding_is_an_error(self):
        self.assertEqual(level_for(_finding(status=Status.ESCALATE)), ERROR)

    def test_a_repair_is_a_warning_not_an_error(self):
        self.assertEqual(level_for(_finding(status=Status.REPAIR)), WARNING)

    def test_a_lexical_finding_is_only_ever_a_note(self):
        """A claim we cannot prove must not render as a compiler error would."""
        self.assertEqual(
            level_for(_finding(confidence=Confidence.LEXICAL)), NOTE)

    def test_an_external_finding_is_only_ever_a_note(self):
        self.assertEqual(
            level_for(_finding(confidence=Confidence.EXTERNAL)), NOTE)

    def test_an_advisory_rule_is_a_note_however_severe_it_is_configured(self):
        self.assertEqual(level_for(_finding(status=Status.BLOCK), advisory=True), NOTE)


class TestWhichRulesAreAdvisory(unittest.TestCase):
    def test_shape_rules_are_advisory_by_default(self):
        self.assertIn("file_too_long", advisory_rules(Policy()))

    def test_a_project_that_gates_them_is_reported_as_gating_them(self):
        """Calling them notes would misreport the project's own decision to it."""
        gated = Policy(structure=Structure(gates=True))
        self.assertNotIn("file_too_long", advisory_rules(gated))

    def test_a_loosened_policy_stays_advisory_even_when_gates_are_on(self):
        gated = Policy(structure=Structure(gates=True))
        self.assertIn("policy_weakened", advisory_rules(gated))


class TestFingerprints(unittest.TestCase):
    def test_the_same_finding_keeps_its_identity_when_it_moves(self):
        """A finding pushed down by an edit above it is not a new finding."""
        self.assertEqual(fingerprint(_finding(line=7)), fingerprint(_finding(line=91)))

    def test_a_different_rule_is_a_different_finding(self):
        self.assertNotEqual(fingerprint(_finding()),
                            fingerprint(_finding(rule="file_too_long")))

    def test_the_same_rule_on_a_different_symbol_is_a_different_finding(self):
        self.assertNotEqual(fingerprint(_finding(symbol="a")),
                            fingerprint(_finding(symbol="b")))


class TestTheDocument(unittest.TestCase):
    def setUp(self):
        self.verdict = Verdict.of(
            [_finding()], skipped=["src/app.ts: no rule in this policy applies"])
        self.run = build(self.verdict, version="9.9.9")["runs"][0]

    def test_it_is_valid_json_at_the_declared_version(self):
        payload = json.loads(dumps(self.verdict))
        self.assertEqual(payload["version"], "2.1.0")

    def test_each_finding_becomes_one_result_with_a_location(self):
        location = self.run["results"][0]["locations"][0]["physicalLocation"]
        self.assertEqual(location["artifactLocation"]["uri"], "src/pay.py")
        self.assertEqual(location["region"]["startLine"], 7)

    def test_the_message_carries_the_fix_as_well_as_the_finding(self):
        self.assertIn("Restore it.", self.run["results"][0]["message"]["text"])

    def test_every_rule_that_fired_is_declared_once(self):
        self.assertEqual([r["id"] for r in self.run["tool"]["driver"]["rules"]],
                         ["assertion_monotonicity"])

    def test_a_file_nothing_could_read_is_a_notification_not_a_result(self):
        """"No rule could read this" is not a finding about the code."""
        notes = self.run["invocations"][0]["toolExecutionNotifications"]
        self.assertEqual(len(notes), 1)
        self.assertIn("src/app.ts", notes[0]["message"]["text"])
        self.assertEqual(len(self.run["results"]), 1)

    def test_a_line_number_is_never_below_one(self):
        """SARIF regions are 1-based; zero makes a platform drop the result."""
        run = build(Verdict.of([_finding(line=0)]))["runs"][0]
        self.assertEqual(
            run["results"][0]["locations"][0]["physicalLocation"]["region"]["startLine"], 1)


class TestThroughTheCommand(unittest.TestCase):
    """CI parses this, so stdout must always be a document or nothing at all."""

    def setUp(self):
        import subprocess
        import tempfile
        from pathlib import Path as _Path

        self.root = _Path(tempfile.mkdtemp())
        for args in (["init", "-q", "-b", "main", "."],
                     ["config", "user.email", "t@t"], ["config", "user.name", "T"]):
            subprocess.run(["git", *args], cwd=self.root, capture_output=True)
        (self.root / "a.py").write_text("x = 1\n")
        subprocess.run(["git", "add", "-A"], cwd=self.root, capture_output=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=self.root,
                       capture_output=True)

    def _run(self, *extra):
        from tests.test_cli import run

        _, out, _ = run(["review", "--root", str(self.root), *extra])
        return out

    def test_nothing_but_the_document_reaches_stdout(self):
        """The basis line and the pacing bar would corrupt a parsed payload."""
        (self.root / "b.py").write_text("y = 2\n")
        out = self._run("--sarif")
        self.assertEqual(json.loads(out)["version"], "2.1.0")

    def test_a_clean_tree_still_emits_a_document(self):
        """Empty stdout cannot be told from a command that fell over."""
        payload = json.loads(self._run("--sarif"))
        self.assertEqual(payload["runs"][0]["results"], [])

    def test_the_empty_document_says_why_it_is_empty(self):
        """An unqualified pass would be the green banner in its quietest form."""
        payload = json.loads(self._run("--sarif"))
        notes = payload["runs"][0]["invocations"][0]["toolExecutionNotifications"]
        self.assertIn("no uncommitted changes", notes[0]["message"]["text"])

    def test_the_json_form_does_the_same(self):
        payload = json.loads(self._run("--json"))
        self.assertEqual(payload["status"], "unverified")
        self.assertEqual(list(payload["skipped"]), ["no uncommitted changes to check"])


if __name__ == "__main__":
    unittest.main()
