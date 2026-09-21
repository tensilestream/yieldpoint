"""Rules a project declares for itself.

The review asked for "no new `os.getenv` outside the config module". That is
not one rule — it is the shape almost every project-specific rule has: a call
that belongs in one place and nowhere else. Expressing it needs the complement
of a path, which the custom-rule mechanism could not say.
"""

import json
import tempfile
import unittest
from pathlib import Path

from yieldpoint.core.metrics import measure
from yieldpoint.verify import verify_change

RULE = {
    "name": "config_read_outside_config",
    "forbid_call": "os.getenv",
    "allow_in": "**/config.py",
    "message": "Read configuration through the config module, not here.",
}
SOURCE = 'import os\n\n\ndef f():\n    return os.getenv("TOKEN")\n'


def _policy(rule=RULE):
    path = Path(tempfile.mkdtemp()) / "c.json"
    path.write_text(json.dumps({"structure": {"custom": [rule]}}))
    return str(path)


def _rules_for(path, policy=None):
    verdict = verify_change(None, SOURCE, path, policy or _policy())
    return [f.rule for f in verdict.findings]


class TestAllowIn(unittest.TestCase):
    def test_the_call_is_reported_where_it_does_not_belong(self):
        self.assertIn("config_read_outside_config", _rules_for("src/pay.py"))

    def test_the_exempt_file_is_left_alone(self):
        self.assertNotIn("config_read_outside_config", _rules_for("src/config.py"))

    def test_the_exemption_matches_at_the_repository_root_too(self):
        self.assertNotIn("config_read_outside_config", _rules_for("config.py"))

    def test_an_exemption_carves_out_of_a_broad_path_rather_than_competing(self):
        """`path` selects where a rule applies; `allow_in` must win inside it."""
        rule = {**RULE, "path": "src/**"}
        self.assertIn("config_read_outside_config", _rules_for("src/pay.py", _policy(rule)))
        self.assertNotIn("config_read_outside_config",
                         _rules_for("src/config.py", _policy(rule)))

    def test_without_an_exemption_nothing_is_exempt(self):
        rule = {k: v for k, v in RULE.items() if k != "allow_in"}
        self.assertIn("config_read_outside_config", _rules_for("src/config.py", _policy(rule)))


class TestCallsAreRecordedAsWritten(unittest.TestCase):
    """A rule that is on and can never match is worse than one that is off.

    Only the bare attribute was recorded, so `"forbid_call": "os.getenv"` — the
    spelling any reader would choose — configured a rule that never fired and
    said nothing about it.
    """

    def setUp(self):
        self.calls = measure(
            'import os\n\n\ndef f():\n'
            '    return os.getenv("T") + os.environ.get("U") + open("z")\n').calls

    def test_the_dotted_spelling_is_recorded(self):
        self.assertEqual(self.calls["os.getenv"], 1)

    def test_the_bare_spelling_still_is(self):
        self.assertEqual(self.calls["getenv"], 1)

    def test_two_levels_of_attribute_are_recorded_whole(self):
        self.assertEqual(self.calls["os.environ.get"], 1)

    def test_a_plain_function_call_is_unaffected(self):
        self.assertEqual(self.calls["open"], 1)

    def test_a_dotted_rule_matches_what_the_source_says(self):
        rule = {**RULE, "forbid_call": "os.environ.get", "allow_in": ""}
        verdict = verify_change(
            None, 'import os\n\n\ndef f():\n    return os.environ.get("U")\n',
            "src/pay.py", _policy(rule))
        self.assertEqual([f.rule for f in verdict.findings],
                         ["config_read_outside_config"])


if __name__ == "__main__":
    unittest.main()
