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

    def test_a_change_set_is_profiled_as_one_task(self):
        data = build_profile([
            Change("src/total.py", SOURCE, SOURCE + "\n# explain\n"),
            Change("src/other.py", SOURCE, SOURCE + "\n# explain\n"),
        ]).to_dict()
        self.assertEqual(data["change"]["files"], 2)
        self.assertEqual(data["change"]["added_lines"], 4)
        self.assertEqual(data["coverage"]["analysed_paths"],
                         ["src/other.py", "src/total.py"])

    def test_the_riskiest_file_decides_the_tier_for_the_whole_set(self):
        """A task containing one risky file is a risky task. Averaging it away
        would route the set on its easiest member."""
        calm = Change("src/total.py", SOURCE, SOURCE + "\n# explain\n")
        alone = build_profile(calm).to_dict()
        together = build_profile([calm, Change("sdk/node/src/router.js", "export {}",
                                               "export const x = 1")]).to_dict()
        self.assertEqual(alone["tier"]["value"], "small")
        self.assertEqual(together["tier"]["value"], "capable")
        self.assertEqual(together["risk"]["value"], "moderate")

    def test_requirements_accumulate_across_the_change_set(self):
        data = build_profile([
            Change("src/total.py", SOURCE, SOURCE + "\n# explain\n"),
            Change("sdk/node/src/router.js", "export {}", "export const x = 1"),
        ]).to_dict()
        self.assertEqual(sorted(data["requirements"]["capabilities"]),
                         ["large_context", "multilingual_sdk", "strong_reasoning", "tool_use"])
        self.assertEqual(data["requirements"]["minimum_context_window"], "large")

    def test_one_unreadable_file_makes_the_whole_set_inexact(self):
        data = build_profile([
            Change("src/total.py", SOURCE, SOURCE + "\n# explain\n"),
            Change("src/router.js", "export {}", "export const x = 1"),
        ]).to_dict()
        self.assertFalse(data["coverage"]["exact_analysis"])
        self.assertEqual(data["coverage"]["unverified_paths"], ["src/router.js"])
        self.assertEqual(data["coverage"]["languages"], ["javascript", "python"])

    def test_a_single_change_profiles_exactly_as_it_did_before(self):
        """Passing one Change must stay byte-identical: the fixtures, the shared
        digests and every existing host depend on it."""
        change = Change("src/total.py", SOURCE, SOURCE + "\n# explain\n")
        self.assertEqual(build_profile(change).to_dict(),
                         build_profile([change]).to_dict())

    def test_an_empty_change_set_is_refused(self):
        with self.assertRaises(ValueError):
            build_profile([])

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


if __name__ == "__main__":
    unittest.main()
