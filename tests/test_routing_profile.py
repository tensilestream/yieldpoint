"""The provider-neutral profile remains deterministic and conservative."""

from __future__ import annotations

import unittest
import json
from pathlib import Path

from yieldpoint.core.policy import Policy
from yieldpoint.harness import (
    CapsuleInput, Change, HandoffRequest, ProfileContext, admit, build_profile, build_task_capsule, can_handoff, handoff,
    middleware,
    session_from, validate_profile,
)


SOURCE = "def total(items):\n    return sum(items)\n"


class TestRoutingProfile(unittest.TestCase):
    def test_same_change_has_the_same_profile_id(self):
        change = Change("src/total.py", SOURCE, SOURCE + "\n# explain\n")
        self.assertEqual(build_profile(change).to_dict(), build_profile(change).to_dict())

    def test_unanalysed_language_is_explicit_and_needs_capable_context(self):
        profile = build_profile(Change("src/router.js", "export {}", "export const x = 1"))
        data = profile.to_dict()
        self.assertFalse(data["coverage"]["exact_analysis"])
        self.assertEqual(data["verification"]["status"], "unverified")
        self.assertIn("large_context", data["requirements"]["capabilities"])

    def test_release_path_requires_the_cross_sdk_checks(self):
        data = build_profile(Change("sdk/java/pom.xml", "<x/>", "<x>v</x>")).to_dict()
        self.assertEqual(data["verification"]["required"], [
            "package_consumer", "release_preflight", "unit_tests",
        ])
        self.assertIn("multilingual_sdk", data["requirements"]["capabilities"])

    def test_baseline_debt_does_not_change_the_tier(self):
        change = Change("src/total.py", SOURCE, SOURCE + "\n# explain\n")
        plain = build_profile(change).to_dict()
        with_baseline = build_profile(
            change, context=ProfileContext(baseline_findings=99)).to_dict()
        self.assertEqual(plain["tier"], with_baseline["tier"])
        self.assertEqual(with_baseline["change"]["baseline_findings"], 99)

    def test_assess_adds_the_profile_without_changing_existing_keys(self):
        result = middleware().assess(Change("src/total.py", SOURCE, SOURCE))
        self.assertEqual(set(result) - {"routing_profile"}, {"signals", "risk", "tier"})
        self.assertEqual(result["routing_profile"]["schema_version"], 1)

    def test_shared_fixtures_are_transport_compatible(self):
        root = Path(__file__).resolve().parent.parent / "fixtures" / "routing-profile"
        profile = validate_profile(json.loads((root / "valid-profile.json").read_text()))
        session = session_from(json.loads((root / "valid-session.json").read_text()))
        self.assertEqual(profile.profile_id, session.profile_id)
        with self.assertRaises(ValueError):
            validate_profile(json.loads((root / "invalid-profile.json").read_text()))


class TestRoutingSessionPolicy(unittest.TestCase):
    def test_valid_session_limits_are_loaded(self):
        policy = Policy.load({"routing_session": {
            "enabled": True, "max_model_switches": 2,
            "capsule_max_chars": 4000, "router_overhead_fraction": 0.1,
        }})
        self.assertTrue(policy.routing_session.enabled)
        self.assertEqual(policy.routing_session.max_model_switches, 2)
        self.assertEqual(policy.routing_session.capsule_max_chars, 4000)

    def test_invalid_session_limits_keep_safe_defaults(self):
        policy = Policy.load({"routing_session": {
            "max_model_switches": 9, "capsule_max_chars": 1,
            "router_overhead_fraction": 1,
        }})
        self.assertEqual(policy.routing_session.max_model_switches, 1)
        self.assertEqual(policy.routing_session.capsule_max_chars, 12_000)
        self.assertEqual(policy.routing_session.router_overhead_fraction, 0.05)
        self.assertEqual(len(policy.warnings), 3)


class TestStickyRoutingSession(unittest.TestCase):
    def setUp(self):
        self.profile = build_profile(Change(
            "src/total.py", SOURCE, SOURCE + "\n# explain\n",
        )).to_dict()
        self.session = admit(self.profile, task_id="task-1", selected_model="small")

    def test_normal_work_cannot_switch_models(self):
        allowed, reason = can_handoff(
            self.session, self.profile, HandoffRequest("normal_work", candidate_capabilities=frozenset({"code_generation"})),
        )
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

    def test_capsule_keeps_findings_and_drops_optional_context_first(self):
        context = CapsuleInput(
            "Fix total", ("Tests pass",),
            {"status": "repair", "findings": [{"rule": "boundary_violation"}]},
            ("src/total.py",), "x" * 20_000, ("verbose" * 1000,),
        )
        capsule = build_task_capsule(self.session.to_dict(), self.profile, context=context)
        self.assertIn("diff_excerpt", capsule["truncated"])
        self.assertEqual(capsule["verification"]["findings"][0]["rule"], "boundary_violation")
        self.assertTrue(capsule["digest"].startswith("sha256:"))


if __name__ == "__main__":
    unittest.main()
