"""Policy loading: severity is configuration, and bad config degrades loudly."""

import json
import tempfile
import unittest
from pathlib import Path

from yieldpoint.core.policy import Policy
from yieldpoint.core.verdict import Status


class TestDefaults(unittest.TestCase):
    def test_defaults_protect_common_test_layouts(self):
        policy = Policy()
        for path in ("tests/test_a.py", "src/a_test.py", "src/a.spec.ts", "pkg/fixtures/x.json"):
            self.assertTrue(policy.protects(path), path)

    def test_defaults_do_not_protect_ordinary_source(self):
        policy = Policy()
        for path in ("src/latest.py", "src/testimonial.tsx", "yieldpoint/core/diff.py"):
            self.assertFalse(policy.protects(path), path)


class TestSeverityIsConfiguration(unittest.TestCase):
    def test_rule_value_sets_returned_status(self):
        policy = Policy.from_dict({"test_contract": {"assertion_monotonicity": "escalate"}})
        self.assertIs(policy.test_contract.assertion_monotonicity, Status.ESCALATE)

    def test_off_disables_a_rule(self):
        policy = Policy.from_dict({"test_contract": {"forbid_vacuous_assertions": "off"}})
        self.assertIsNone(policy.test_contract.forbid_vacuous_assertions)

    def test_false_also_disables_a_rule(self):
        policy = Policy.from_dict({"test_contract": {"forbid_new_skip_markers": False}})
        self.assertIsNone(policy.test_contract.forbid_new_skip_markers)

    def test_unknown_severity_warns_and_falls_back(self):
        policy = Policy.from_dict({"test_contract": {"assertion_monotonicity": "nuke"}})
        self.assertIs(policy.test_contract.assertion_monotonicity, Status.REPAIR)
        self.assertTrue(any("nuke" in w for w in policy.warnings))


class TestMalformedConfig(unittest.TestCase):
    def test_zone_without_path_is_dropped_with_a_warning(self):
        policy = Policy.from_dict({"boundaries": {"zones": [{"name": "broken"}]}})
        self.assertEqual(policy.boundaries.zones, ())
        self.assertTrue(any("missing 'path'" in w for w in policy.warnings))

    def test_non_object_section_warns_rather_than_crashing(self):
        policy = Policy.from_dict({"boundaries": "everything"})
        self.assertTrue(any("must be an object" in w for w in policy.warnings))

    def test_non_integer_window_falls_back(self):
        policy = Policy.from_dict({"loop_breaker": {"window": "six"}})
        self.assertEqual(policy.loop_breaker.window, 6)
        self.assertTrue(policy.warnings)

    def test_window_below_one_falls_back(self):
        policy = Policy.from_dict({"loop_breaker": {"window": 0}})
        self.assertEqual(policy.loop_breaker.window, 6)

    def test_empty_config_yields_usable_defaults(self):
        policy = Policy.from_dict({})
        self.assertEqual(policy.warnings, ())
        self.assertIs(policy.test_contract.assertion_monotonicity, Status.REPAIR)


class TestLoading(unittest.TestCase):
    def test_load_from_file_and_discover_upward(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".yieldpoint.json").write_text(
                json.dumps({"project": {"name": "demo"}}), encoding="utf-8"
            )
            nested = root / "a" / "b"
            nested.mkdir(parents=True)

            self.assertEqual(Policy.load(root / ".yieldpoint.json").project_name, "demo")
            self.assertEqual(Policy.load(root).project_name, "demo")
            # .resolve() on both sides: macOS symlinks /var -> /private/var.
            self.assertEqual(
                Policy.discover(nested), (root / ".yieldpoint.json").resolve()
            )

    def test_discover_returns_none_rather_than_guessing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(Policy.discover(Path(tmp)))

    def test_invalid_json_names_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".yieldpoint.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                Policy.load(path)
            self.assertIn(".yieldpoint.json", str(ctx.exception))

    def test_missing_file_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                Policy.load(Path(tmp) / ".yieldpoint.json")

    def test_policy_passes_through_unchanged(self):
        policy = Policy(project_name="already-loaded")
        self.assertIs(Policy.load(policy), policy)


class TestRepositoryOwnPolicy(unittest.TestCase):
    """Yieldpoint's own .yieldpoint.json must stay loadable and warning-free."""

    def test_repo_policy_loads_cleanly(self):
        policy = Policy.load(Path(__file__).resolve().parent.parent / ".yieldpoint.json")
        self.assertEqual(policy.warnings, ())
        self.assertEqual(policy.project_name, "Yieldpoint")
        self.assertEqual(len(policy.boundaries.zones), 2)


if __name__ == "__main__":
    unittest.main()
