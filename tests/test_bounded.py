"""Delivering part of a result, and never delivering it silently.

The saving and the risk are the same number: the lines a reader did not see.
So every test here is really one test asked several ways — does the result
that reaches the model say what is missing from it?
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from yieldpoint.bounded import failures, head
from yieldpoint.core.policy import Policy
from yieldpoint.recall import Unavailable, digest, keep, recall

MANY = "\n".join(f"src/f{i}.py:{i}: match" for i in range(300))


class HeadCase(unittest.TestCase):
    def test_keeps_the_front_and_declares_the_rest(self):
        result = head(MANY, limit=10, handle="abc")
        self.assertEqual(result.kept, 10)
        self.assertEqual(result.omitted, 290)
        self.assertIs(result.complete, False)
        self.assertIn("290 more line(s) not shown", result.text)
        self.assertIn("yieldpoint recall abc", result.text)

    def test_the_kept_lines_are_the_original_lines(self):
        result = head(MANY, limit=3, handle="abc")
        self.assertEqual(result.text.splitlines()[:3], MANY.splitlines()[:3])

    def test_a_short_result_is_returned_whole_and_unmarked(self):
        result = head("a\nb", limit=10)
        self.assertEqual(result.text, "a\nb")
        self.assertIs(result.complete, True)
        self.assertNotIn("not shown", result.text)

    def test_without_a_handle_the_omission_is_still_declared(self):
        """No way to fetch it is not a reason to stop saying it is missing."""
        result = head(MANY, limit=5)
        self.assertIn("295 more line(s) not shown", result.text)
        self.assertNotIn("recall", result.text)


class FailuresCase(unittest.TestCase):
    def test_keeps_the_lines_that_explain_the_failure(self):
        log = "\n".join(["ok"] * 200 + ["E   AssertionError: boom"] + ["ok"] * 200)
        result = failures(log, handle="h")
        self.assertIn("E   AssertionError: boom", result.text)
        self.assertEqual(result.omitted, 400)
        self.assertIn("400 more line(s) not shown", result.text)

    def test_a_log_with_no_recognisable_failure_keeps_its_tail(self):
        """Guessing wrong is survivable only because the omission is declared."""
        log = "\n".join(f"step {i}" for i in range(500))
        result = failures(log, handle="h")
        self.assertIn("step 499", result.text)
        self.assertIn("not shown", result.text)

    def test_a_short_log_is_returned_whole(self):
        log = "\n".join(f"step {i}" for i in range(5))
        self.assertIs(failures(log).complete, True)


class RecallCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.on = Policy.from_dict({"metrics": {"retain_omitted": True}})
        self.off = Policy.from_dict({"metrics": {}})

    def test_retention_is_off_unless_asked_for(self):
        """Nothing else here writes content to disk; this must be deliberate."""
        self.assertEqual(keep("secret", root=self.root, policy=self.off), "")

    def test_a_stored_original_comes_back_byte_for_byte(self):
        handle = keep(MANY, root=self.root, policy=self.on)
        self.assertEqual(handle, digest(MANY))
        self.assertEqual(recall(handle, root=self.root, policy=self.on), MANY)

    def test_an_unknown_handle_is_an_error_not_an_empty_answer(self):
        with self.assertRaises(Unavailable):
            recall("0" * 16, root=self.root, policy=self.on)

    def test_a_handle_cannot_walk_out_of_the_store(self):
        for attempt in ("../../etc/passwd", "a/b", ""):
            with self.assertRaises(Unavailable):
                recall(attempt, root=self.root, policy=self.on)

    def test_tampered_content_is_refused_rather_than_returned(self):
        """A wrong original is worse than none: the omission looks recovered."""
        handle = keep(MANY, root=self.root, policy=self.on)
        (self.root / ".yieldpoint" / "recall" / handle).write_text("not it")
        with self.assertRaises(Unavailable):
            recall(handle, root=self.root, policy=self.on)


if __name__ == "__main__":
    unittest.main()
