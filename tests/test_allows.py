"""An escape hatch with no inventory is indistinguishable from a disabled rule.

From the review: *"otherwise allows quietly becomes decorative."* Nobody can
tell three considered exceptions from three hundred reflexes without a list,
and the count only ever goes one way.
"""

import subprocess
import tempfile
import unittest
from pathlib import Path

from yieldpoint.allows import Allow, collect, render, to_dict
from yieldpoint.core.acknowledge import covers, scan
from yieldpoint.core.policy import Policy

ACK = "# yieldpoint: allow file_too_long - owed a split, tracked in issue 12\n"


def _git(args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, check=False)


def _repo(files):
    root = Path(tempfile.mkdtemp())
    _git(["init", "-q", "-b", "main", "."], root)
    _git(["config", "user.email", "t@t"], root)
    _git(["config", "user.name", "Tester"], root)
    for name, text in files.items():
        (root / name).write_text(text)
    _git(["add", "-A"], root)
    _git(["-c", "user.name=Tester", "commit", "-qm", "base"], root)
    return root


class TestDocumentationIsNotASuppression(unittest.TestCase):
    """An acknowledgement written *about* acknowledgements is not one.

    This package's own module docstring carried an example that silenced any
    monotonicity finding on the three lines beneath it.
    """

    DOCSTRING = (
        '"""Explains the syntax.\n\n'
        "    # yieldpoint: allow assertion_monotonicity - an example\n"
        '"""\n\nx = 1\n'
    )

    def test_an_example_in_a_docstring_does_not_suppress(self):
        self.assertEqual(scan(self.DOCSTRING), {})

    def test_it_does_not_cover_the_lines_beneath_it(self):
        self.assertIs(covers(scan(self.DOCSTRING), "assertion_monotonicity", 4), False)

    def test_a_real_comment_still_suppresses(self):
        source = "x = 1\n# yieldpoint: allow file_too_long - real\ny = 2\n"
        self.assertIs(covers(scan(source), "file_too_long", 3), True)

    def test_a_trailing_comment_on_a_statement_still_suppresses(self):
        source = "x = 1  # yieldpoint: allow file_too_long - real\ny = 2\n"
        self.assertIs(covers(scan(source), "file_too_long", 2), True)

    def test_a_file_that_will_not_tokenize_keeps_the_old_behaviour(self):
        """Losing every acknowledgement in an unparseable file would be worse."""
        source = "def f(:\n# yieldpoint: allow file_too_long - still counts\n"
        self.assertIn(2, scan(source))

    def test_a_string_that_merely_mentions_the_syntax_is_not_one(self):
        source = 'MESSAGE = "write # yieldpoint: allow file_too_long - reason"\nx = 1\n'
        self.assertEqual(scan(source), {})


class TestCollect(unittest.TestCase):
    def test_it_finds_an_acknowledgement_and_dates_it(self):
        root = _repo({"a.py": ACK + "x = 1\n"})
        found = collect(root, Policy())
        self.assertEqual([(a.file, a.line, a.rule) for a in found],
                         [("a.py", 1, "file_too_long")])
        self.assertRegex(found[0].written, r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual(found[0].author, "Tester")

    def test_the_reason_is_carried_through(self):
        root = _repo({"a.py": ACK + "x = 1\n"})
        self.assertIn("issue 12", collect(root, Policy())[0].reason)

    def test_a_tree_with_none_reports_none(self):
        self.assertEqual(collect(_repo({"a.py": "x = 1\n"}), Policy()), [])

    def test_a_file_outside_git_is_listed_without_a_date(self):
        """Absent is reported as absent, never as the epoch."""
        root = Path(tempfile.mkdtemp())
        (root / "a.py").write_text(ACK + "x = 1\n")
        found = collect(root, Policy())
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].written, "")
        self.assertIs(found[0].dated, False)

    def test_undated_entries_sort_last_rather_than_first(self):
        """An unknown date is not the oldest date."""
        entries = [Allow("b.py", 1, "r", "x"), Allow("a.py", 1, "r", "y", "2020-01-01")]
        ordered = sorted(entries, key=lambda a: (not a.dated, a.written, a.file, a.line))
        self.assertEqual([a.file for a in ordered], ["a.py", "b.py"])


class TestRender(unittest.TestCase):
    def test_an_empty_tree_says_so_without_implying_a_clean_bill(self):
        text = render([])
        self.assertIn("No acknowledgements", text)

    def test_it_counts_each_rule(self):
        text = render([Allow("a.py", 1, "file_too_long", "x", "2026-01-01"),
                       Allow("b.py", 2, "file_too_long", "y", "2026-01-02")])
        self.assertIn("file_too_long  (2)", text)

    def test_it_says_an_acknowledgement_is_not_an_off_switch(self):
        self.assertIn("not an off switch",
                      render([Allow("a.py", 1, "r", "x", "2026-01-01")]))

    def test_it_says_the_dates_do_not_move(self):
        """Otherwise a reader assumes ages drift and stops trusting the report."""
        self.assertIn("same tomorrow",
                      render([Allow("a.py", 1, "r", "x", "2026-01-01")]))

    def test_undated_entries_are_called_out_rather_than_blended_in(self):
        self.assertIn("no date", render([Allow("a.py", 1, "r", "x")]))

    def test_the_machine_readable_form_carries_every_field(self):
        payload = to_dict([Allow("a.py", 3, "r", "why", "2026-01-01", "Tester")])
        self.assertEqual(payload["acknowledgements"][0],
                         {"file": "a.py", "line": 3, "rule": "r", "reason": "why",
                          "written": "2026-01-01", "author": "Tester"})


if __name__ == "__main__":
    unittest.main()
