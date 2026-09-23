"""Integrity of the checks themselves.

An agent that cannot weaken an assertion can still weaken the build that runs it.
Analysis is lexical, so these findings warn and are structurally barred from
blocking — that guarantee is asserted here, not assumed.
"""

import unittest

from yieldpoint.core.policy import ContinuousIntegration, Policy
from yieldpoint.core.verdict import Confidence, Status
from yieldpoint.core.workflows import (
    CI_CHECK_DISABLED,
    CI_CHECK_REMOVED,
    check,
    steps_of,
)
from yieldpoint.verify import verify_change

WORKFLOW = """name: CI
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Unit tests
        run: python -m unittest discover -q
      - name: Lint
        run: ruff check .
  release:
    runs-on: ubuntu-latest
    steps:
      - run: ./scripts/release-check.sh
"""

PATH = ".github/workflows/ci.yml"
CONFIG = ContinuousIntegration()


def rules(before, after, config=CONFIG):
    return [f.rule for f in check(before, after, PATH, config)[0]]


class TestExtraction(unittest.TestCase):
    def test_actions_and_commands_are_both_steps(self):
        identities = {step.identity for step in steps_of(WORKFLOW)}
        self.assertIn("uses:actions/checkout", identities)
        self.assertIn("run:python -m unittest discover -q", identities)

    def test_an_action_is_identified_without_its_pin(self):
        """Otherwise every dependency bump reads as a removal."""
        bumped = WORKFLOW.replace("actions/checkout@v4", "actions/checkout@v7")
        self.assertEqual(
            {step.identity for step in steps_of(WORKFLOW)},
            {step.identity for step in steps_of(bumped)},
        )
        self.assertEqual(rules(WORKFLOW, bumped), [])

    def test_a_local_action_keeps_its_path(self):
        source = "jobs:\n  a:\n    steps:\n      - uses: ./.github/actions/setup\n"
        self.assertEqual(steps_of(source)[0].identity,
                         "uses:./.github/actions/setup")

    def test_every_step_is_found(self):
        self.assertEqual(len(steps_of(WORKFLOW)), 4)

    def test_block_scalar_commands(self):
        source = (
            "jobs:\n  a:\n    steps:\n      - name: Two things\n        run: |\n"
            "          python one.py\n          python two.py\n"
        )
        self.assertEqual(
            [step.identity for step in steps_of(source)],
            ["run:python one.py", "run:python two.py"],
        )

    def test_bookkeeping_is_not_a_check(self):
        source = "jobs:\n  a:\n    steps:\n      - run: VERSION=1\n      - run: git add file\n"
        self.assertEqual(steps_of(source), ())

    def test_empty_input(self):
        self.assertEqual(steps_of(""), ())


class TestRemoval(unittest.TestCase):
    def test_deleting_a_job_reports_its_steps(self):
        trimmed = WORKFLOW[: WORKFLOW.index("  release:")]
        self.assertEqual(rules(WORKFLOW, trimmed), [CI_CHECK_REMOVED])

    def test_deleting_one_step(self):
        after = WORKFLOW.replace("      - name: Lint\n        run: ruff check .\n", "")
        self.assertEqual(rules(WORKFLOW, after), [CI_CHECK_REMOVED])

    def test_adding_a_step_is_not_a_finding(self):
        after = WORKFLOW + "      - run: echo extra\n"
        self.assertEqual(rules(WORKFLOW, after), [])

    def test_an_unchanged_workflow_is_silent(self):
        self.assertEqual(rules(WORKFLOW, WORKFLOW), [])


class TestDisabling(unittest.TestCase):
    def test_suppressed_with_or_true(self):
        after = WORKFLOW.replace("run: ruff check .", "run: ruff check . || true")
        self.assertEqual(rules(WORKFLOW, after), [CI_CHECK_DISABLED])

    def test_suppressed_with_semicolon_true(self):
        after = WORKFLOW.replace("run: ruff check .", "run: ruff check . ; true")
        self.assertEqual(rules(WORKFLOW, after), [CI_CHECK_DISABLED])

    def test_continue_on_error(self):
        after = WORKFLOW.replace(
            "      - name: Lint\n", "      - name: Lint\n        continue-on-error: true\n")
        self.assertEqual(rules(WORKFLOW, after), [CI_CHECK_DISABLED])

    def test_gated_on_false(self):
        after = WORKFLOW.replace(
            "      - name: Lint\n", "      - name: Lint\n        if: false\n")
        self.assertEqual(rules(WORKFLOW, after), [CI_CHECK_DISABLED])

    def test_a_job_level_suppression_disables_its_steps(self):
        after = WORKFLOW.replace(
            "  release:\n    runs-on: ubuntu-latest\n",
            "  release:\n    continue-on-error: true\n    runs-on: ubuntu-latest\n")
        self.assertEqual(rules(WORKFLOW, after), [CI_CHECK_DISABLED])

    def test_suppression_is_disabling_not_replacement(self):
        """`|| true` must read as the same step, disabled — not remove-plus-add."""
        after = WORKFLOW.replace("run: ruff check .", "run: ruff check . || true")
        self.assertNotIn(CI_CHECK_REMOVED, rules(WORKFLOW, after))

    def test_a_real_conditional_is_not_a_suppression(self):
        after = WORKFLOW.replace(
            "      - name: Lint\n",
            "      - name: Lint\n        if: github.event_name == 'push'\n")
        self.assertEqual(rules(WORKFLOW, after), [])


class TestDifferential(unittest.TestCase):
    def test_an_already_disabled_step_is_not_reported_again(self):
        disabled = WORKFLOW.replace("run: ruff check .", "run: ruff check . || true")
        self.assertEqual(rules(disabled, disabled + "      - run: echo new\n"), [])

    def test_re_enabling_a_step_is_silent(self):
        disabled = WORKFLOW.replace("run: ruff check .", "run: ruff check . || true")
        self.assertEqual(rules(disabled, WORKFLOW), [])


class TestConfiguration(unittest.TestCase):
    def test_rules_can_be_disabled_independently(self):
        after = WORKFLOW.replace("run: ruff check .", "run: ruff check . || true")
        config = ContinuousIntegration(check_disabled=None)
        self.assertEqual(rules(WORKFLOW, after, config), [])

    def test_severity_comes_from_policy(self):
        after = WORKFLOW.replace("run: ruff check .", "run: ruff check . || true")
        config = ContinuousIntegration(check_disabled=Status.ESCALATE)
        self.assertIs(check(WORKFLOW, after, PATH, config)[0][0].status, Status.ESCALATE)


class TestConfidence(unittest.TestCase):
    """Lexical analysis of YAML may be wrong, so it must never gate work."""

    def test_findings_are_marked_lexical(self):
        after = WORKFLOW.replace("run: ruff check .", "run: ruff check . || true")
        self.assertIs(check(WORKFLOW, after, PATH, CONFIG)[0][0].confidence, Confidence.LEXICAL)

    def test_a_lexical_finding_cannot_be_configured_to_block(self):
        after = WORKFLOW.replace("run: ruff check .", "run: ruff check . || true")
        config = ContinuousIntegration(check_disabled=Status.BLOCK)
        with self.assertRaises(ValueError):
            check(WORKFLOW, after, PATH, config)


class TestIntegration(unittest.TestCase):
    def test_workflow_files_are_verified(self):
        after = WORKFLOW.replace("run: ruff check .", "run: ruff check . || true")
        verdict = verify_change(WORKFLOW, after, PATH, Policy())
        self.assertIs(verdict.status, Status.REPAIR)
        self.assertEqual(verdict.checked, (PATH,))

    def test_pre_commit_config_is_verified(self):
        before = "repos:\n  - repo: local\n    hooks:\n      - id: tests\n        entry: pytest\n"
        verdict = verify_change(before, "repos: []\n", ".pre-commit-config.yaml", Policy())
        self.assertTrue(verdict.findings)

    def test_unrelated_yaml_is_not_treated_as_ci(self):
        verdict = verify_change(WORKFLOW, "name: other\n", "config/settings.yml", Policy())
        self.assertEqual(verdict.findings, ())
        self.assertEqual(verdict.checked, ())

    def test_this_repositorys_own_workflow_parses(self):
        from pathlib import Path

        source = (Path(__file__).resolve().parent.parent / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertGreater(len(steps_of(source)), 5)


if __name__ == "__main__":
    unittest.main()
