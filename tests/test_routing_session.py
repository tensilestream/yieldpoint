"""The sticky session: one selection, one bounded, evidence-backed handoff."""

from __future__ import annotations

import json
import unittest

from yieldpoint.core.policy import Policy
from yieldpoint.harness import (
    CapsuleInput, Change, HandoffRequest, ProfileContext, admit, build_profile,
    build_task_capsule, can_handoff, handoff, session_from,
)


SOURCE = "def total(items):\n    return sum(items)\n"

#: Everything the shipped decision table can ask a candidate for, so a test
#: about one condition is never accidentally a test about a missing capability.
ALL_CAPABILITIES = frozenset({
    "tool_use", "strong_reasoning", "large_context", "code_generation",
    "multilingual_sdk",
})

REPAIR = {"schema_version": 1, "status": "repair",
          "findings": [{"rule": "boundary_violation"}]}


def _enabled(**overrides) -> Policy:
    return Policy.load({"routing_session": {"enabled": True, **overrides}})


def _profile_with(verdict, policy=None, **kwargs) -> dict:
    change = Change("src/total.py", SOURCE, SOURCE + "\n# explain\n")
    return build_profile(change, policy,
                         context=ProfileContext(verdict=verdict, **kwargs)).to_dict()


class TestStickyRoutingSession(unittest.TestCase):
    def setUp(self):
        self.profile = _profile_with(REPAIR)
        self.session = admit(self.profile, task_id="task-1", selected_model="small")

    def _request(self, event: str, **kwargs) -> HandoffRequest:
        kwargs.setdefault("candidate_capabilities", ALL_CAPABILITIES)
        return HandoffRequest(event, **kwargs)

    def test_normal_work_cannot_switch_models(self):
        allowed, reason = can_handoff(self.session, self.profile, self._request("normal_work"))
        self.assertFalse(allowed)
        self.assertIn("checkpoint", reason)

    def test_failed_verification_can_switch_once(self):
        allowed, _ = can_handoff(
            self.session, self.profile, HandoffRequest(
                "verification_failed", candidate_capabilities=frozenset({"code_generation", "tool_use", "strong_reasoning"})),
        )
        self.assertTrue(allowed)
        request = HandoffRequest(
            "verification_failed", "capable",
            frozenset({"code_generation", "tool_use", "strong_reasoning"}),
        )
        upgraded = handoff(self.session, self.profile, request)
        self.assertEqual(upgraded.switch_count, 1)
        self.assertEqual(upgraded.selected_model, "capable")
        self.assertFalse(can_handoff(upgraded, self.profile, HandoffRequest(
            "repair_exhausted", candidate_capabilities=frozenset({"code_generation", "tool_use", "strong_reasoning"})),
        )[0])
        self.assertIn("budget is exhausted", can_handoff(
            upgraded, self.profile, self._request("repair_exhausted"))[1])

    def test_a_settled_verdict_does_not_buy_another_model(self):
        """A pass needs no second opinion, and a block is a person's decision."""
        for status, expected in (("pass", "pass"), ("block", "block")):
            with self.subTest(status):
                profile = _profile_with({"status": status})
                session = admit(profile, task_id=f"task-{status}")
                allowed, reason = can_handoff(session, profile,
                                              self._request("verification_failed"))
                self.assertFalse(allowed)
                self.assertIn(expected, reason)

    def test_an_unverified_change_does_not_escalate_by_default(self):
        unverified = _profile_with(None)
        session = admit(unverified, task_id="task-unverified")
        allowed, reason = can_handoff(session, unverified, self._request("verification_failed"))
        self.assertFalse(allowed)
        self.assertIn("unverified", reason)

    def test_allow_unverified_is_the_documented_override(self):
        profile = _profile_with(None, _enabled(allow_unverified=True))
        session = admit(profile, task_id="task-override")
        allowed, reason = can_handoff(session, profile, self._request("verification_failed"))
        self.assertTrue(allowed)
        self.assertEqual(reason, "explicit checkpoint permits one model handoff")

    def test_an_unconfigured_checkpoint_is_refused(self):
        profile = _profile_with(REPAIR, _enabled(checkpoint_events=["loop_tripped"]))
        session = admit(profile, task_id="task-events")
        refused, reason = can_handoff(session, profile, self._request("verification_failed"))
        self.assertFalse(refused)
        self.assertIn("loop_tripped", reason)
        configured, _ = can_handoff(session, profile, self._request("loop_tripped"))
        self.assertTrue(configured)

    def test_overhead_beyond_the_budget_is_refused(self):
        request = self._request("verification_failed", estimated_overhead_fraction=0.19)
        allowed, reason = can_handoff(self.session, self.profile, request)
        self.assertFalse(allowed)
        self.assertIn("budget", reason)
        within, _ = can_handoff(self.session, self.profile, self._request(
            "verification_failed", estimated_overhead_fraction=0.04))
        self.assertTrue(within)

    def test_a_candidate_missing_one_capability_is_refused(self):
        required = sorted(self.profile["requirements"]["capabilities"])
        short = frozenset(set(required) - {required[0]})
        allowed, reason = can_handoff(self.session, self.profile,
                                      HandoffRequest("verification_failed",
                                                     candidate_capabilities=short))
        self.assertFalse(allowed)
        self.assertIn(required[0], reason)

    def test_a_session_cannot_be_used_with_another_profile(self):
        other = build_profile(Change("src/other.py", SOURCE, SOURCE + "\n#\n"),
                              context=ProfileContext(verdict=REPAIR)).to_dict()
        allowed, reason = can_handoff(self.session, other, self._request("verification_failed"))
        self.assertFalse(allowed)
        self.assertIn("does not belong", reason)

    def test_state_survives_a_reload_and_decides_the_same_way(self):
        reloaded = session_from(json.loads(json.dumps(self.session.to_dict())))
        self.assertEqual(reloaded, self.session)
        self.assertEqual(can_handoff(reloaded, self.profile, self._request("verification_failed")),
                         can_handoff(self.session, self.profile, self._request("verification_failed")))

    def test_capsule_keeps_findings_and_drops_optional_context_first(self):
        context = CapsuleInput(
            "Fix total", ("Tests pass",), REPAIR,
            ("src/total.py",), "x" * 20_000, ("verbose" * 1000,),
        )
        capsule = build_task_capsule(self.session.to_dict(), self.profile, context=context)
        self.assertIn("diff_excerpt", capsule["truncated"])
        self.assertEqual(capsule["verification"]["findings"][0]["rule"], "boundary_violation")
        self.assertTrue(capsule["digest"].startswith("sha256:"))

    def test_a_capsule_never_exceeds_the_budget_it_declares(self):
        profile = {**self.profile, "handoff": {**self.profile["handoff"], "capsule_max_chars": 1_000}}
        capsule = build_task_capsule(self.session.to_dict(), profile, context=CapsuleInput(
            "o" * 150, ("criterion",), REPAIR, ("src/total.py",), "x" * 9_000))
        encoded = json.dumps(capsule, sort_keys=True, separators=(",", ":"))
        self.assertLessEqual(len(encoded), 1_000)


if __name__ == "__main__":
    unittest.main()
