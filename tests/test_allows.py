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
        payload = to_dict([Allow("a.py", 3, "r", "why", "2026-01-01", "Tester",
                                 until="2026-12-01", owner="platform")])
        self.assertEqual(payload["acknowledgements"][0],
                         {"file": "a.py", "line": 3, "rule": "r", "reason": "why",
                          "written": "2026-01-01", "author": "Tester",
                          "until": "2026-12-01", "owner": "platform"})


if __name__ == "__main__":
    unittest.main()


class TestExpiryNeverChangesAVerdict(unittest.TestCase):
    """An expiry is a note to a human, not an input to a rule.

    If a passing date made an acknowledgement stop suppressing, the same commit
    would pass today and fail tomorrow with nothing changed — the one thing
    RULES.md section 4 forbids. So the rules ignore it entirely, and a command
    that announces it is reading the clock enforces it instead.
    """

    LONG = "\n".join(f"x{i} = 1" for i in range(400)) + "\n"

    def _verdict(self, until):
        import json as _json

        from yieldpoint.verify import verify_change

        policy = Path(tempfile.mkdtemp()) / "c.json"
        policy.write_text(_json.dumps({"structure": {"max_file_lines": 300}}))
        source = f"# yieldpoint: allow file_too_long until {until} - owed\n" + self.LONG
        return verify_change("", source, "big.py", str(policy))

    def test_an_acknowledgement_long_past_its_date_still_suppresses(self):
        self.assertEqual(
            [f.rule for f in self._verdict("2000-01-01").findings], [])

    def test_one_not_yet_due_suppresses_identically(self):
        self.assertEqual(
            [f.rule for f in self._verdict("2999-01-01").findings], [])

    def test_the_suppression_is_recorded_rather_than_lost(self):
        """Acknowledged is not the same as never found."""
        self.assertEqual(len(self._verdict("2000-01-01").acknowledged), 1)


class TestExpirySyntax(unittest.TestCase):
    def _mark(self, text):
        return scan(text + "\ny = 1\n")[1][0]

    def test_a_date_is_captured(self):
        self.assertEqual(
            self._mark("# yieldpoint: allow file_too_long until 2026-12-01 - owed").until,
            "2026-12-01")

    def test_an_owner_is_captured(self):
        self.assertEqual(
            self._mark("# yieldpoint: allow file_too_long owner=platform - owed").owner,
            "platform")

    def test_both_together(self):
        mark = self._mark(
            "# yieldpoint: allow file_too_long until 2026-12-01 owner=platform - owed")
        self.assertEqual((mark.until, mark.owner, mark.reason),
                         ("2026-12-01", "platform", "owed"))

    def test_the_word_until_inside_a_reason_is_not_an_expiry(self):
        """`until` matches only a date-shaped token, after the rule name."""
        mark = self._mark("# yieldpoint: allow file_too_long - keep until the rewrite")
        self.assertEqual(mark.until, "")
        self.assertEqual(mark.reason, "keep until the rewrite")

    def test_the_old_form_is_unchanged(self):
        mark = self._mark("# yieldpoint: allow file_too_long - owed a split")
        self.assertEqual((mark.until, mark.owner, mark.reason),
                         ("", "", "owed a split"))


class TestTheOnlyCommandThatReadsAClock(unittest.TestCase):
    def _found(self):
        return [
            Allow("a.py", 1, "r", "gone", "2026-01-01", "T", until="2026-01-01"),
            Allow("b.py", 2, "r", "fine", "2026-01-01", "T", until="2099-01-01"),
            Allow("c.py", 3, "r", "bad", "2026-01-01", "T", until="2026-13-45"),
            Allow("d.py", 4, "r", "none", "2026-01-01", "T"),
        ]

    def test_only_dates_in_the_past_are_expired(self):
        from yieldpoint.allows import expired

        past, _ = expired(self._found(), "2026-09-22")
        self.assertEqual([a.file for a in past], ["a.py"])

    def test_an_unparseable_date_is_neither_expired_nor_fine(self):
        from yieldpoint.allows import expired

        past, unreadable = expired(self._found(), "2026-09-22")
        self.assertEqual([a.file for a in unreadable], ["c.py"])
        self.assertNotIn("c.py", [a.file for a in past])

    def test_an_acknowledgement_with_no_expiry_is_never_considered(self):
        from yieldpoint.allows import expired

        past, unreadable = expired(self._found(), "2999-01-01")
        self.assertNotIn("d.py", [a.file for a in past + unreadable])

    def test_the_report_names_the_date_it_judged_against(self):
        from yieldpoint.allows import expired, render_expired

        past, unreadable = expired(self._found(), "2026-09-22")
        text = render_expired(past, unreadable, "2026-09-22")
        self.assertIn("2026-09-22", text)
        self.assertIn("different day", text)

    def test_nothing_expired_says_so_without_implying_none_exist(self):
        from yieldpoint.allows import render_expired

        self.assertIn("No acknowledgement has passed its date",
                      render_expired([], [], "2026-09-22"))

    def test_the_inventory_says_expiry_is_not_enforced_there(self):
        text = render([Allow("a.py", 1, "r", "x", "2026-01-01", until="2026-01-01")])
        self.assertIn("never enforced here", text)
        self.assertIn("--expired", text)


class TestAnAcknowledgementIsNotAnOffSwitch(unittest.TestCase):
    """Review item #6: *"a finding when an allowed file gets worse despite the
    allow. Otherwise allows quietly becomes decorative."*

    Measured before this was built: a file acknowledged at 400 lines reached
    900 in complete silence. The comment answered the debt once and then
    answered everything after it.
    """

    def setUp(self):
        import json as _json

        self.policy = Path(tempfile.mkdtemp()) / "c.json"
        self.policy.write_text(_json.dumps(
            {"structure": {"max_file_lines": 300, "max_change_lines": 5000}}))

    def _file(self, lines):
        return ("# yieldpoint: allow file_too_long - owed a split\n"
                + "\n".join(f"x{i} = 1" for i in range(lines)) + "\n")

    def _verdict(self, before, after):
        from yieldpoint.verify import verify_change

        return verify_change(self._file(before), self._file(after), "big.py",
                             str(self.policy))

    def _lengths(self, verdict):
        return [f for f in verdict.findings if f.rule == "file_too_long"]

    def test_growing_an_acknowledged_file_is_reported_again(self):
        self.assertEqual(len(self._lengths(self._verdict(400, 900))), 1)

    def test_the_message_says_what_the_acknowledgement_did_and_did_not_answer(self):
        from yieldpoint.core.acknowledge import STILL_GROWING

        self.assertEqual(self._lengths(self._verdict(400, 900))[0].prescription,
                         STILL_GROWING)

    def test_leaving_it_alone_stays_silent(self):
        verdict = self._verdict(400, 400)
        self.assertEqual(self._lengths(verdict), [])

    def test_paying_it_down_stays_silent(self):
        """Shrinking a file is not something to be told off for."""
        self.assertEqual(self._lengths(self._verdict(900, 400)), [])

    def test_it_is_still_reported_rather_than_enforced(self):
        """The point is that the growth is visible, not that it is refused."""
        from yieldpoint.core.policy import Policy
        from yieldpoint.hook import blocks

        self.assertIs(blocks(self._verdict(400, 900), Policy()), False)

    def test_an_unacknowledged_file_is_unaffected(self):
        from yieldpoint.verify import verify_change

        plain = lambda n: "\n".join(f"x{i} = 1" for i in range(n)) + "\n"
        verdict = verify_change(plain(400), plain(900), "big.py", str(self.policy))
        found = [f for f in verdict.findings if f.rule == "file_too_long"]
        self.assertEqual(len(found), 1)
        self.assertNotIn("acknowledged", found[0].prescription)

    def test_a_finding_this_change_introduced_is_still_fully_acknowledged(self):
        """The comment answers what the author wrote on purpose."""
        from yieldpoint.verify import verify_change

        verdict = verify_change("", self._file(400), "new.py", str(self.policy))
        self.assertEqual(self._lengths(verdict), [])
        self.assertEqual([f.rule for f in verdict.acknowledged], ["file_too_long"])
