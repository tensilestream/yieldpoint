"""A handler that catches everything and records nothing.

The closest of the shape rules to this package's actual subject: a broad,
silent handler converts a failure into a success, so a test covering that path
keeps passing while verifying nothing. It is also the cheapest way out of a red
test, which is why something under pressure to go green reaches for it.
"""

import unittest

from yieldpoint.core.swallow import SWALLOWED_EXCEPTION, check, find
from yieldpoint.core.verdict import Confidence, Status


def _fn(handler, caught="Exception"):
    return f"def f():\n    try:\n        g()\n    except {caught}:\n        {handler}\n"


class TestBreadth(unittest.TestCase):
    """Naming the exception you expect is the considered decision."""

    def test_catching_exception_and_discarding_is_reported(self):
        self.assertEqual(len(find(_fn("pass"))), 1)

    def test_a_bare_except_is_reported(self):
        self.assertEqual(len(find("def f():\n    try:\n        g()\n    except:\n        pass\n")), 1)

    def test_base_exception_is_reported(self):
        self.assertEqual(len(find(_fn("pass", "BaseException"))), 1)

    def test_a_named_exception_is_not(self):
        self.assertEqual(find(_fn("pass", "KeyError")), [])

    def test_a_tuple_containing_exception_still_catches_everything(self):
        self.assertEqual(len(find(_fn("pass", "(KeyError, Exception)"))), 1)

    def test_a_tuple_of_named_exceptions_is_not_reported(self):
        self.assertEqual(find(_fn("pass", "(KeyError, OSError)")), [])


class TestSilence(unittest.TestCase):
    """A handler that leaves a trace has made a choice a reader can see."""

    def test_pass_is_silent(self):
        self.assertEqual(len(find(_fn("pass"))), 1)

    def test_ellipsis_is_silent(self):
        self.assertEqual(len(find(_fn("..."))), 1)

    def test_a_bare_return_is_silent(self):
        self.assertEqual(len(find(_fn("return"))), 1)

    def test_returning_none_explicitly_is_silent(self):
        self.assertEqual(len(find(_fn("return None"))), 1)

    def test_logging_is_not(self):
        self.assertEqual(find(_fn("log(exc)")), [])

    def test_re_raising_is_not(self):
        self.assertEqual(find(_fn("raise")), [])

    def test_returning_a_substitute_value_is_not(self):
        """The caller still gets something, and the choice is visible."""
        self.assertEqual(find(_fn("return {}")), [])


class TestWhereItIs(unittest.TestCase):
    def test_a_method_is_named_by_its_qualified_name(self):
        source = ("class C:\n    def m(self):\n        try:\n            g()\n"
                  "        except Exception:\n            pass\n")
        self.assertEqual(find(source)[0].function, "C.m")

    def test_a_handler_outside_any_function_is_still_found(self):
        found = find("try:\n    g()\nexcept Exception:\n    pass\n")
        self.assertEqual([s.function for s in found], [""])

    def test_source_that_does_not_parse_yields_nothing_rather_than_raising(self):
        self.assertEqual(find("def f(:\n"), [])


class TestOnlyWhatThisChangeAdded(unittest.TestCase):
    def test_a_handler_already_there_is_not_this_change_s_doing(self):
        source = _fn("pass")
        self.assertEqual(check(source, source, "a.py", Status.REPAIR), [])

    def test_a_handler_this_change_added_is_reported(self):
        clean = "def f():\n    g()\n"
        found = check(clean, _fn("pass"), "a.py", Status.REPAIR)
        self.assertEqual([f.rule for f in found], [SWALLOWED_EXCEPTION])
        self.assertIs(found[0].confidence, Confidence.EXACT)

    def test_a_second_handler_beside_an_existing_one_is_reported_once(self):
        before = _fn("pass")
        after = before + "\ndef h():\n    try:\n        g()\n    except Exception:\n        pass\n"
        self.assertEqual(len(check(before, after, "a.py", Status.REPAIR)), 1)

    def test_a_new_file_full_of_them_is_all_reported(self):
        self.assertEqual(len(check(None, _fn("pass"), "a.py", Status.REPAIR)), 1)

    def test_switching_the_severity_off_switches_the_rule_off(self):
        self.assertEqual(check("def f():\n    g()\n", _fn("pass"), "a.py", None), [])


class TestThroughVerify(unittest.TestCase):
    def test_it_reaches_a_verdict_on_a_non_test_file(self):
        from yieldpoint.verify import verify_change

        verdict = verify_change("def f():\n    g()\n", _fn("pass"), "src/pay.py")
        self.assertIn(SWALLOWED_EXCEPTION, [f.rule for f in verdict.findings])

    def test_the_detail_says_what_was_lost_rather_than_naming_a_style(self):
        from yieldpoint.verify import verify_change

        verdict = verify_change("def f():\n    g()\n", _fn("pass"), "src/pay.py")
        detail = next(f for f in verdict.findings
                      if f.rule == SWALLOWED_EXCEPTION).detail
        self.assertIn("looks like success", detail)


if __name__ == "__main__":
    unittest.main()


class TestTheRuleFoundOneHere(unittest.TestCase):
    """`swallowed_exception` reported `backtest._replay` on the run that built it.

    The handler was not conflating failure with success — a commit that could
    not be replayed was already counted separately and reported. What it
    discarded was *why*, so a verifier crash and a merge commit git cannot show
    arrived as the same number.
    """

    def test_a_replay_that_could_not_run_says_why(self):
        from yieldpoint.backtest import Replay

        self.assertEqual(Replay(reason="git could not show this commit").verdict, None)

    def test_a_crash_in_the_verifier_is_named_as_one(self):
        import pathlib
        from unittest import mock

        from yieldpoint import backtest

        with mock.patch.object(backtest, "verify_diff", side_effect=RuntimeError("boom")), \
                mock.patch.object(backtest, "_git") as git:
            git.return_value = mock.Mock(returncode=0, stdout="--- a/x\n+++ b/x\n")
            replay = backtest._replay(pathlib.Path("."), "abc1234", None)
        self.assertIn("RuntimeError", replay.reason)
        self.assertIn("boom", replay.reason)
        self.assertIsNone(replay.verdict)
