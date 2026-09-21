"""The tunable surface, derived rather than described.

A config can state every value in force and still leave an agent guessing at
which keys exist, what types they take and what switching one off looks like.
A comment block written at install time would answer that for exactly one
version. These tests hold the answer to the running build instead.
"""

import ast
import json
import tempfile
import unittest
from dataclasses import fields, is_dataclass
from pathlib import Path

from yieldpoint.core.policy import Policy
from yieldpoint.schema import Setting, render, settings, to_dict

#: Both halves of the parser: the reader validates, the fields module
#: names what it reads. The numeric limits are only in the second.
READER = (Path("yieldpoint/core/policyreader.py"),
          Path("yieldpoint/core/policyfields.py"))
FIELDS = Path("yieldpoint/core/policysections.py")


def _literals(sources) -> set[str]:
    """Every string constant in the policy reader.

    Not just the arguments to ``raw.get(...)``: the reader pulls its numeric
    limits with ``raw.get(field)`` while looping over a tuple of names, so
    scanning call arguments alone finds none of them. A first version of this
    test did exactly that and passed while the schema was missing
    ``max_nesting`` — vacuously green, which is the failure this package exists
    to report. Collecting every literal and intersecting with the real field
    names below is coarser and actually bites.
    """
    found = set()
    for source in sources:
        found.update(
            node.value
            for node in ast.walk(ast.parse(source.read_text(encoding="utf-8")))
            if isinstance(node, ast.Constant) and isinstance(node.value, str))
    return found


def _configurable_names() -> set[str]:
    """Every field name on every policy section."""
    policy = Policy()
    names = set()
    for section in fields(policy):
        block = getattr(policy, section.name)
        if is_dataclass(block):
            names.update(f.name for f in fields(block))
    return names


class TestNothingShipsUndocumented(unittest.TestCase):
    def test_every_key_the_parser_accepts_is_listed(self):
        """A setting the reader honours but the schema omits is a silent option.

        Driven off the reader's own source, so adding an option without
        listing it fails here rather than being discovered by a user guessing.
        """
        listed = {s.name for s in settings(Policy())}
        # Section names are containers, not settings, and are listed as their
        # contents; internal bookkeeping is not configurable at all.
        containers = {f.name for f in fields(Policy())
                      if is_dataclass(getattr(Policy(), f.name))}
        # Only names that are genuinely settings: a literal in the reader that
        # is not a field on any section is prose, not an option.
        accepted = _literals(READER) & _configurable_names()
        missing = accepted - listed - containers
        self.assertTrue(accepted, "the scan found no settings at all")
        self.assertEqual(missing, set(), "read by the parser but absent from `yieldpoint policy`")

    def test_every_dataclass_field_in_a_section_is_listed(self):
        policy = Policy()
        expected = {f"{section.name}.{field.name}"
                    for section in fields(policy)
                    if is_dataclass(getattr(policy, section.name))
                    for field in fields(getattr(policy, section.name))}
        listed = {s.key for s in settings(policy)}
        self.assertEqual(expected - listed, set(), "a section field nothing lists")


class TestProvenance(unittest.TestCase):
    """`limit 50 (default)` and `limit 50 (.yieldpoint.json)` need different edits."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.path = self.root / ".yieldpoint.json"
        self.path.write_text(json.dumps({"structure": {"max_lines": 77}}))

    def _find(self, key):
        found = settings(Policy.load(str(self.path)), str(self.path))
        return next(s for s in found if s.key == key)

    def test_a_value_from_the_file_is_attributed_to_the_file(self):
        setting = self._find("structure.max_lines")
        self.assertEqual(setting.value, 77)
        self.assertEqual(setting.source, ".yieldpoint.json")
        self.assertTrue(setting.changed)

    def test_a_value_never_written_down_is_attributed_to_the_default(self):
        setting = self._find("structure.max_parameters")
        self.assertEqual(setting.source, "default")
        self.assertFalse(setting.changed)

    def test_the_default_is_shown_beside_the_value_in_force(self):
        setting = self._find("structure.max_lines")
        self.assertEqual(setting.default, 50)
        self.assertNotEqual(setting.default, setting.value)


class TestLegalValues(unittest.TestCase):
    def _find(self, key):
        return next(s for s in settings(Policy()) if s.key == key)

    def test_a_severity_lists_the_severities_and_how_to_switch_it_off(self):
        legal = self._find("test_contract.assertion_monotonicity").legal
        for word in ("repair", "escalate", "block", "null"):
            self.assertIn(word, legal)

    def test_an_optional_limit_says_how_to_remove_the_limit(self):
        self.assertIn("null for no limit", self._find("structure.max_file_lines").legal)

    def test_a_required_limit_does_not_offer_a_null_that_would_be_ignored(self):
        self.assertNotIn("null", self._find("structure.max_lines").legal)

    def test_a_list_of_objects_is_not_described_as_a_list_of_strings(self):
        self.assertIn("objects", self._find("boundaries.zones").legal)

    def test_a_list_of_strings_is(self):
        self.assertEqual(self._find("linters.tools").legal, "a list of strings")


class TestNotesComeFromTheSource(unittest.TestCase):
    def test_a_field_docstring_reaches_the_reader(self):
        """Read from the module that declares the field, so the two cannot drift."""
        note = next(s for s in settings(Policy()) if s.key == "structure.max_file_lines").note
        self.assertIn("Lines of code a file may hold", note)

    def test_the_note_is_the_one_written_beside_the_field(self):
        declared = FIELDS.read_text(encoding="utf-8")
        self.assertIn("Lines of code a file may hold", declared)


class TestOutput(unittest.TestCase):
    def test_the_machine_readable_form_is_json(self):
        payload = json.loads(json.dumps(to_dict(settings(Policy()))))
        self.assertEqual(
            sorted(payload["settings"][0]),
            ["default", "key", "legal", "note", "source", "type", "value"])
        self.assertEqual(len(payload["settings"]), len(settings(Policy())))

    def test_a_repository_with_no_config_says_so_rather_than_showing_a_path(self):
        text = render(settings(Policy()), None)
        self.assertIn("no .yieldpoint.json found", text)

    def test_the_output_says_that_loosening_a_limit_is_itself_reported(self):
        self.assertIn("policy_weakened", render(settings(Policy()), None))


if __name__ == "__main__":
    unittest.main()


class TestDrift(unittest.TestCase):
    """Freezing the thresholds keeps a verdict stable across upgrades.

    The cost is that a repository never *gains* an improved default either, and
    nothing told it so. This is the command that does — and the one thing it
    must not do is claim to know which frozen values were deliberate.
    """

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.path = self.root / ".yieldpoint.json"

    def _settings(self, raw):
        self.path.write_text(json.dumps(raw))
        return settings(Policy.load(str(self.path)), str(self.path))

    def test_a_value_matching_the_default_is_not_drift(self):
        from yieldpoint.schema import drifted

        found = self._settings({"structure": {"max_lines": 50}})
        self.assertEqual([s.key for s in drifted(found)], [])

    def test_a_value_differing_from_the_default_is(self):
        from yieldpoint.schema import drifted

        found = self._settings({"structure": {"max_lines": 77}})
        self.assertIn("structure.max_lines", [s.key for s in drifted(found)])

    def test_a_default_never_written_down_is_not_drift(self):
        """Only what the repository states can be stale."""
        from yieldpoint.schema import drifted

        found = self._settings({})
        self.assertEqual([s.key for s in drifted(found)], [])

    def _report(self, stamp="0.1.0", running="9.9.9", raw=None):
        from yieldpoint.schema import render_drift

        return render_drift(
            self._settings(raw or {"structure": {"max_lines": 77}}), stamp, running)

    def test_the_report_names_both_values(self):
        text = self._report()
        self.assertIn("77", text)
        self.assertIn("50", text)

    def test_it_says_which_build_wrote_the_policy(self):
        text = self._report()
        self.assertIn("written by 0.1.0", text)
        self.assertIn("running 9.9.9", text)

    def test_a_policy_with_no_stamp_says_it_does_not_know(self):
        self.assertIn("does not record which build wrote it",
                      self._report(stamp=""))

    def test_it_admits_it_cannot_tell_a_choice_from_a_frozen_default(self):
        self.assertIn("look the same here", self._report())

    def test_it_changes_nothing(self):
        raw = {"structure": {"max_lines": 77}}
        self._report(raw=raw)
        self.assertEqual(json.loads(self.path.read_text()), raw)


class TestTheStamp(unittest.TestCase):
    def test_a_freshly_written_policy_records_the_build(self):
        from yieldpoint import __version__
        from yieldpoint.policyfile import ensure, written_by

        root = Path(tempfile.mkdtemp())
        ensure(root)
        self.assertEqual(written_by(root), __version__)

    def test_a_policy_without_one_reports_absence_rather_than_guessing(self):
        from yieldpoint.policyfile import written_by

        root = Path(tempfile.mkdtemp())
        (root / ".yieldpoint.json").write_text('{"version": 1}')
        self.assertEqual(written_by(root), "")

    def test_the_stamp_does_not_stop_the_policy_being_read(self):
        from yieldpoint.policyfile import ensure

        root = Path(tempfile.mkdtemp())
        ensure(root)
        self.assertEqual(
            Policy.load(str(root / ".yieldpoint.json")).structure.max_lines, 50)
