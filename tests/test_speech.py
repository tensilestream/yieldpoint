"""Stage 8 gate: a verdict must survive being heard, and assent being misheard."""

import unittest

from yieldpoint.core.policy import Policy
from yieldpoint.core.verdict import Finding, Status, Verdict
from yieldpoint.speech import _WORDS, speak
from yieldpoint.verify import verify_change

BEFORE = (
    'def test_total():\n    inv = build()\n'
    '    assert inv.total == 42\n    assert inv.currency == "USD"\n'
)
WEAKER = (
    'def test_total():\n    inv = build()\n'
    '    assert inv.total is not None\n    assert inv.currency == "USD"\n'
)
PATH = "tests/test_invoice.py"


def verdict_for(after, before=BEFORE):
    return verify_change(before, after, PATH, Policy())


def finding(**kwargs):
    defaults = dict(rule="assertion_monotonicity", status=Status.REPAIR, file=PATH,
                    line=1, detail="Assertion on x was removed.", prescription="restore")
    defaults.update(kwargs)
    return Finding(**defaults)


class TestSummary(unittest.TestCase):
    def test_clean_change(self):
        self.assertIn("Assertions held", speak(verdict_for(BEFORE)).summary)

    def test_problem_is_counted_and_named(self):
        summary = speak(verdict_for(WEAKER)).summary
        self.assertIn("1 problem", summary)
        self.assertIn("verify less than before", summary)

    def test_phrase_covers_removal_and_downgrade_alike(self):
        """assertion_monotonicity fires on both; a phrase naming one would mislead."""
        removed = speak(verdict_for('def test_total():\n    assert inv.currency == "USD"\n'))
        self.assertIn("verify less than before", removed.summary)

    def test_unverified_files_are_announced(self):
        summary = speak(verify_change(BEFORE, WEAKER, "tests/a.test.ts", Policy())).summary
        self.assertIn("could not be verified", summary)

    def test_deletion_is_mentioned_even_when_clean(self):
        summary = speak(Verdict.of([], checked=[PATH]), deletions=(PATH,)).summary
        self.assertIn("would be deleted", summary)

    def test_plurals_agree(self):
        self.assertIn("1 file checked", speak(Verdict.of([], checked=[PATH])).summary)
        self.assertIn("2 files checked", speak(Verdict.of([], checked=[PATH, "b.py"])).summary)


class TestDetails(unittest.TestCase):
    def test_details_name_the_subject_not_just_the_rule(self):
        details = speak(verdict_for(WEAKER)).details
        self.assertIn("inv.total", details[0])

    def test_two_findings_say_different_things(self):
        details = speak(verdict_for(None)).details
        self.assertNotEqual(details[0], details[1])

    def test_screen_notation_is_removed(self):
        spoken = " ".join(speak(verdict_for(WEAKER)).details)
        self.assertNotIn("->", spoken)
        self.assertNotIn("non_null", spoken)
        self.assertIn("not null", spoken)

    def test_paths_are_spoken_as_names(self):
        utterance = speak(Verdict.of([finding(symbol=None)]))
        self.assertIn("test invoice", utterance.details[0])
        self.assertNotIn("tests/", utterance.details[0])

    def test_long_lists_are_truncated_with_a_count(self):
        findings = [finding(line=i, detail=f"Assertion on x{i} was removed.") for i in range(6)]
        details = speak(Verdict.of(findings), max_details=2).details
        self.assertEqual(len(details), 3)
        self.assertIn("4 more problems", details[-1])


class TestConfirmation(unittest.TestCase):
    def test_routine_repair_does_not_interrupt(self):
        self.assertIsNone(speak(verdict_for(WEAKER)).confirmation)

    def test_deletion_requires_assent(self):
        utterance = speak(Verdict.of([], checked=[PATH]), deletions=(PATH,))
        self.assertTrue(utterance.requires_assent)

    def test_escalation_requires_assent(self):
        utterance = speak(Verdict.of([finding(status=Status.ESCALATE)]))
        self.assertTrue(utterance.requires_assent)

    def test_several_removals_require_assent(self):
        removals = [finding(line=1), finding(line=2)]
        self.assertTrue(speak(Verdict.of(removals), confirm_threshold=2).requires_assent)

    def test_threshold_is_configurable(self):
        self.assertIsNone(speak(Verdict.of([finding()]), confirm_threshold=5).confirmation)

    def test_question_states_the_reason(self):
        question = speak(Verdict.of([], checked=[PATH]), deletions=(PATH,)).confirmation.question
        self.assertIn("would be deleted", question)
        self.assertIn("cancel", question)


class TestToken(unittest.TestCase):
    """Assent must be a specific word, never an incidental one."""

    def setUp(self):
        self.confirmation = speak(
            Verdict.of([], checked=[PATH]), deletions=(PATH,)
        ).confirmation

    def test_token_is_deterministic(self):
        again = speak(Verdict.of([], checked=[PATH]), deletions=(PATH,)).confirmation
        self.assertEqual(self.confirmation.token, again.token)

    def test_different_changes_get_different_tokens(self):
        other = speak(Verdict.of([], checked=["b.py"]), deletions=("b.py",)).confirmation
        self.assertNotEqual(self.confirmation.token, other.token)

    def test_transcription_noise_is_tolerated(self):
        token = self.confirmation.token
        for spoken in (token, token.upper(), f"um, {token}.", f"okay so {token}!", f" {token} "):
            self.assertTrue(self.confirmation.matches(spoken), spoken)

    def test_yes_is_not_assent(self):
        for spoken in ("yes", "yeah okay", "sure go ahead", "yes please", ""):
            self.assertFalse(self.confirmation.matches(spoken), spoken)

    def test_a_different_token_is_not_assent(self):
        """Every word in the list except the real one must be rejected.

        Previously this named four words literally, which passed only while the
        derived token happened not to be one of them — so any change to the
        verdict shape could fail it for a reason unrelated to confirmation.
        """
        others = [w for w in _WORDS if w != self.confirmation.token]
        self.assertEqual(len(others), len(_WORDS) - 1, "token must come from the list")
        for word in others:
            self.assertFalse(self.confirmation.matches(word), word)

    def test_none_input_is_not_assent(self):
        self.assertFalse(self.confirmation.matches(None))


class TestVoicePolicy(unittest.TestCase):
    def test_floor_raises_severity_because_nobody_can_see_the_diff(self):
        policy = Policy()
        self.assertIs(policy.test_contract.assertion_monotonicity, Status.REPAIR)
        self.assertIs(policy.for_voice().test_contract.assertion_monotonicity, Status.ESCALATE)

    def test_floor_never_lowers_an_existing_severity(self):
        policy = Policy.from_dict({
            "test_contract": {"assertion_monotonicity": "block"},
            "voice": {"severity_floor": "repair"},
        })
        self.assertIs(policy.for_voice().test_contract.assertion_monotonicity, Status.BLOCK)

    def test_disabled_rules_stay_disabled(self):
        policy = Policy.from_dict({"test_contract": {"forbid_vacuous_assertions": "off"}})
        self.assertIsNone(policy.for_voice().test_contract.forbid_vacuous_assertions)

    def test_floor_can_be_turned_off(self):
        policy = Policy.from_dict({"voice": {"severity_floor": "off"}})
        self.assertIs(policy.for_voice(), policy)

    def test_voice_escalation_then_triggers_confirmation(self):
        """The two mechanisms compose: raised severity produces a spoken checkpoint."""
        verdict = verify_change(BEFORE, WEAKER, PATH, Policy().for_voice())
        self.assertIs(verdict.status, Status.ESCALATE)
        self.assertTrue(speak(verdict).requires_assent)


class TestUtterance(unittest.TestCase):
    def test_full_orders_summary_then_details_then_question(self):
        utterance = speak(Verdict.of([finding(status=Status.ESCALATE)]))
        text = utterance.full()
        self.assertLess(text.index(utterance.summary), text.index(utterance.details[0]))
        self.assertLess(text.index(utterance.details[0]),
                        text.index(utterance.confirmation.question))


if __name__ == "__main__":
    unittest.main()
