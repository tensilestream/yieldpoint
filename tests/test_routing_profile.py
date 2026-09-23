"""The provider-neutral profile remains deterministic and conservative."""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

from yieldpoint.core.policy import Policy
from yieldpoint.harness import (
    CapsuleInput, Change, HandoffRequest, ProfileContext, admit, build_profile,
    build_task_capsule, can_handoff, handoff, middleware, session_from,
    validate_profile,
)
from yieldpoint.harness.profile import _profile_id


SOURCE = "def total(items):\n    return sum(items)\n"
FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "routing-profile"
ROOT = Path(__file__).resolve().parent.parent

#: Everything the shipped decision table can ask a candidate for, so a test
#: about one condition is never accidentally a test about a missing capability.
ALL_CAPABILITIES = frozenset({
    "tool_use", "strong_reasoning", "large_context", "code_generation",
    "multilingual_sdk",
})

REPAIR = {"schema_version": 1, "status": "repair",
          "findings": [{"rule": "boundary_violation"}]}


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _generator():
    """Load the fixture generator as a module, so the test compares against the
    same code that writes the files rather than a second copy of it."""
    spec = importlib.util.spec_from_file_location(
        "build_routing_fixtures", ROOT / "scripts" / "build_routing_fixtures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _enabled(**overrides) -> Policy:
    return Policy.load({"routing_session": {"enabled": True, **overrides}})


def _profile_with(verdict, policy=None, **kwargs) -> dict:
    change = Change("src/total.py", SOURCE, SOURCE + "\n# explain\n")
    return build_profile(change, policy,
                         context=ProfileContext(verdict=verdict, **kwargs)).to_dict()


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

    def test_an_unanalysable_sdk_file_needs_both_rows_not_the_later_one(self):
        """The rows accumulate. Reporting only the cross-SDK requirement would
        drop `large_context` from the change least safe to analyse blind."""
        data = build_profile(Change("sdk/node/src/router.js", "export {}", "export const x = 1")).to_dict()
        self.assertFalse(data["coverage"]["exact_analysis"])
        self.assertEqual(sorted(data["requirements"]["capabilities"]),
                         ["large_context", "multilingual_sdk", "strong_reasoning", "tool_use"])
        self.assertEqual(data["requirements"]["minimum_context_window"], "large")

    def test_baseline_debt_does_not_change_the_tier(self):
        change = Change("src/total.py", SOURCE, SOURCE + "\n# explain\n")
        plain = build_profile(change).to_dict()
        with_baseline = build_profile(
            change, context=ProfileContext(baseline_findings=99)).to_dict()
        self.assertEqual(plain["tier"], with_baseline["tier"])
        self.assertEqual(with_baseline["change"]["baseline_findings"], 99)

    def test_a_block_verdict_demands_a_person(self):
        data = build_profile(Change("src/total.py", SOURCE, SOURCE + "\n#\n"),
                             context=ProfileContext(verdict={"status": "block"})).to_dict()
        self.assertEqual(data["requirements"]["suggested_policy"], "human_before_land")
        self.assertEqual(data["requirements"]["capabilities"], ["human_review"])

    def test_repair_state_reaches_the_profile(self):
        data = build_profile(
            Change("src/total.py", SOURCE, SOURCE + "\n#\n"),
            context=ProfileContext(verdict=REPAIR, repair_attempt=2, loop_tripped=True),
        ).to_dict()
        self.assertEqual(data["verification"]["repair_attempt"], 2)
        self.assertTrue(data["verification"]["loop_tripped"])
        self.assertEqual(data["verification"]["status"], "repair")

    def test_pace_is_carried_so_budget_pressure_is_visible_at_admission(self):
        data = build_profile(Change("src/total.py", None, "x = 1\n" * 4000)).to_dict()
        self.assertEqual(data["pace"]["value"], "overdue")
        self.assertGreater(data["pace"]["signals"]["budget_used"], 1)

    def test_a_tampered_profile_is_refused(self):
        profile = build_profile(Change("src/total.py", SOURCE, SOURCE + "\n#\n")).to_dict()
        profile["handoff"]["max_model_switches"] = 99
        with self.assertRaises(ValueError):
            validate_profile(profile)

    def test_assess_attaches_the_profile_only_when_routing_is_enabled(self):
        change = Change("src/total.py", SOURCE, SOURCE)
        self.assertEqual(set(middleware().assess(change)), {"signals", "risk", "tier"})
        result = middleware(policy=_enabled()).assess(change)
        self.assertEqual(set(result) - {"routing_profile"}, {"signals", "risk", "tier"})
        self.assertEqual(result["routing_profile"]["schema_version"], 1)


class TestSharedFixtures(unittest.TestCase):
    """The fixtures are the cross-language contract; Node and Java read these."""

    # yieldpoint: allow assertion_monotonicity - the replaced assertion checked
    # `git status` was clean, which fails in any dirty tree regardless of whether
    # the fixtures match. Comparing content is what the test was meant to do.
    def test_the_committed_fixtures_are_current(self):
        """Compared in memory rather than against git, so the check means the
        same thing in a dirty working tree as in a clean one."""
        for name, document in _generator().build().items():
            with self.subTest(name):
                self.assertEqual(_fixture(name), document,
                                 "stale; run scripts/build_routing_fixtures.py")

    def test_valid_fixtures_round_trip(self):
        profile = validate_profile(_fixture("valid-profile.json"))
        session = session_from(_fixture("valid-session.json"))
        self.assertEqual(profile.profile_id, session.profile_id)

    def test_malformed_fixture_is_refused(self):
        with self.assertRaises(ValueError):
            validate_profile(_fixture("invalid-profile.json"))

    def test_every_fixture_profile_digest_matches_its_own_contents(self):
        """A placeholder digest would let all three languages agree on nothing."""
        for name in ("valid-profile.json", "unverified-profile.json", "blocked-profile.json"):
            with self.subTest(name):
                data = _fixture(name)
                body = {key: value for key, value in data.items() if key != "profile_id"}
                self.assertEqual(data["profile_id"], _profile_id(body))

    def test_fixture_statuses_cover_the_routes_the_other_languages_must_handle(self):
        self.assertEqual(_fixture("valid-profile.json")["verification"]["status"], "repair")
        self.assertEqual(_fixture("unverified-profile.json")["verification"]["status"], "unverified")
        blocked = _fixture("blocked-profile.json")
        self.assertEqual(blocked["verification"]["status"], "block")
        self.assertEqual(blocked["requirements"]["capabilities"], ["human_review"])
        self.assertEqual(_fixture("exhausted-session.json")["switch_count"],
                         _fixture("valid-profile.json")["handoff"]["max_model_switches"])

    def test_the_trimmed_capsule_kept_what_matters(self):
        capsule = _fixture("trimmed-capsule.json")
        self.assertEqual(capsule["truncated"], ["diff_excerpt"])
        self.assertEqual(capsule["diff_excerpt"], "")
        self.assertEqual(capsule["objective"], "Charge each line item at its own price")
        self.assertEqual(capsule["acceptance_criteria"],
                         ["boundary_violation is cleared", "unit tests pass"])
        self.assertEqual(capsule["verification"]["findings"][0]["rule"], "boundary_violation")


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

    def test_required_checks_are_configurable_and_validated(self):
        policy = Policy.load({"routing_session": {
            "required_checks": {"cross_sdk_release": ["unit_tests", "not_a_check"]},
        }})
        self.assertEqual(policy.routing_session.required_checks["cross_sdk_release"],
                         ("unit_tests",))
        self.assertTrue(any("not_a_check" in w for w in policy.warnings))

    def test_configured_required_checks_reach_the_profile(self):
        policy = Policy.load({"routing_session": {
            "required_checks": {"cross_sdk_release": ["unit_tests", "integration_tests"]},
        }})
        data = build_profile(Change("sdk/java/pom.xml", "<x/>", "<x>v</x>"), policy).to_dict()
        self.assertEqual(data["verification"]["required"], ["integration_tests", "unit_tests"])

    def test_every_bound_is_published_to_the_other_languages(self):
        data = build_profile(Change("src/total.py", SOURCE, SOURCE + "\n#\n"),
                             _enabled(router_overhead_fraction=0.02)).to_dict()
        self.assertEqual(data["handoff"]["max_overhead_fraction"], 0.02)
        self.assertEqual(data["handoff"]["checkpoint_events"],
                         ["loop_tripped", "repair_exhausted", "verification_failed"])
        self.assertIs(data["handoff"]["allow_unverified"], False)


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
