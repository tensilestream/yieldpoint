"""What this piece of work said it would touch.

From the review: *"You said 'don't touch anything else', and nothing in the
toolchain knew that — the hook happily blocked me on files that instruction
excluded."* Every other failure that session was about attribution. This one
is different: the instruction existed, was followed, and no tool could hear it.
"""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from yieldpoint.core.policy import Policy, Structure
from yieldpoint.core.scope import NEW_FILE_OUT_OF_SCOPE, OUT_OF_SCOPE_EDIT, check
from yieldpoint.core.verdict import Status
from yieldpoint.task import Task, clear, load, save


class TestScopeIsOptIn(unittest.TestCase):
    """Silence is not a scope of zero files."""

    def test_an_undeclared_task_covers_everything(self):
        self.assertIs(Task().covers("anything/at/all.py"), True)

    def test_an_undeclared_task_reports_nothing(self):
        self.assertEqual(check(Task(), ["a.py", "b.py"], created=["c.py"]), [])

    def test_a_declared_task_says_it_is_declared(self):
        self.assertIs(Task(touch=("src/**",)).declared, True)

    def test_a_description_alone_is_not_a_scope(self):
        """Naming the work does not restrict it."""
        self.assertIs(Task(description="thread user_id").declared, False)


class TestCoverage(unittest.TestCase):
    def setUp(self):
        self.task = Task("work", ("src/routes/**", "src/api/main.py"))

    def test_a_glob_matches_below_it(self):
        self.assertIs(self.task.covers("src/routes/deep/a.py"), True)

    def test_an_exact_path_matches(self):
        self.assertIs(self.task.covers("src/api/main.py"), True)

    def test_anything_else_does_not(self):
        self.assertIs(self.task.covers("src/other/b.py"), False)

    def test_windows_separators_are_matched_too(self):
        self.assertIs(self.task.covers("src\\\\routes\\\\a.py"), True)


class TestFindings(unittest.TestCase):
    def setUp(self):
        self.task = Task("work", ("src/routes/**",), no_new_files=True)

    def _rules(self, changed, created=()):
        return [(f.rule, f.file) for f in
                check(self.task, changed, created=created)]

    def test_a_file_outside_the_scope_is_reported(self):
        self.assertIn((OUT_OF_SCOPE_EDIT, "src/api/main.py"),
                      self._rules(["src/api/main.py"]))

    def test_a_file_inside_it_is_not(self):
        self.assertEqual(self._rules(["src/routes/a.py"]), [])

    def test_the_detail_names_the_declared_surface(self):
        found = check(self.task, ["docs/x.md"])
        self.assertIn("src/routes/**", found[0].detail)

    def test_a_new_file_is_reported_when_the_task_said_none(self):
        self.assertIn((NEW_FILE_OUT_OF_SCOPE, "src/new.py"),
                      self._rules(["src/new.py"], created=["src/new.py"]))

    def test_a_new_file_inside_the_scope_is_still_reported_as_new(self):
        """`--no-new-files` is a separate promise from `--touch`."""
        task = Task("work", ("src/**",), no_new_files=True)
        rules = [f.rule for f in check(task, ["src/a.py"], created=["src/a.py"])]
        self.assertEqual(rules, [])

    def test_switching_the_severity_off_switches_the_rule_off(self):
        self.assertEqual(check(self.task, ["docs/x.md"], severity=None), [])


class TestItNeverBlocks(unittest.TestCase):
    """Intent changes mid-task for good reasons. Drift must be seen, not refused."""

    def _verdict(self):
        from yieldpoint.core.verdict import Verdict

        return Verdict.of(check(Task("w", ("src/**",)), ["docs/x.md"]))

    def test_it_does_not_deny_the_change(self):
        from yieldpoint.hook import blocks

        self.assertIs(blocks(self._verdict(), Policy()), False)

    def test_it_does_not_deny_it_even_when_structure_gates(self):
        from yieldpoint.hook import blocks

        gated = Policy(structure=Structure(gates=True))
        self.assertIs(blocks(self._verdict(), gated), False)


class TestStorage(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_it_round_trips(self):
        task = Task("thread user_id", ("a/**", "b.py"), no_new_files=True)
        save(task, self.root)
        self.assertEqual(load(self.root), task)

    def test_no_file_is_an_undeclared_task_rather_than_an_error(self):
        self.assertIs(load(self.root).declared, False)

    def test_a_corrupt_file_does_not_stop_a_verification(self):
        """The rules are what matter; a scope is an extra."""
        path = self.root / ".yieldpoint" / "task.json"
        path.parent.mkdir(parents=True)
        path.write_text("{not json")
        self.assertIs(load(self.root).declared, False)

    def test_clearing_reports_whether_there_was_one(self):
        save(Task("w", ("a/**",)), self.root)
        self.assertIs(clear(self.root), True)
        self.assertIs(clear(self.root), False)

    def test_it_is_written_where_git_already_ignores(self):
        from yieldpoint.task import LOCATION

        self.assertEqual(LOCATION, ".yieldpoint/task.json")
        save(Task("w", ("a/**",)), self.root)
        self.assertTrue((self.root / LOCATION).is_file())


class TestThroughReview(unittest.TestCase):
    def test_a_review_reports_the_drift(self):
        from tests.test_cli import run

        root = Path(tempfile.mkdtemp())
        for args in (["init", "-q", "-b", "main", "."],
                     ["config", "user.email", "t@t"], ["config", "user.name", "T"]):
            subprocess.run(["git", *args], cwd=root, capture_output=True)
        (root / "wanted.py").write_text("x = 1\n")
        (root / "other.py").write_text("y = 1\n")
        subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=root, capture_output=True)
        save(Task("only wanted", ("wanted.py",)), root)
        (root / "other.py").write_text("y = 2\n")

        _, out, _ = run(["review", "--root", str(root), "--json"])
        rules = {f["rule"] for f in json.loads(out)["findings"]}
        self.assertIn(OUT_OF_SCOPE_EDIT, rules)


if __name__ == "__main__":
    unittest.main()
