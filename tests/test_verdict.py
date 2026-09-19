"""The verdict contract is the cross-language API; its shape is load-bearing."""

import json
import unittest

from aegisflow.core.verdict import (
    SCHEMA_VERSION,
    Confidence,
    Finding,
    Status,
    Verdict,
)


def finding(**kwargs) -> Finding:
    defaults = dict(
        rule="assertion_monotonicity",
        status=Status.REPAIR,
        file="tests/test_invoice.py",
        line=41,
        detail="Assertion strength downgraded.",
        prescription="Restore an equality assertion.",
    )
    defaults.update(kwargs)
    return Finding(**defaults)


class TestStatus(unittest.TestCase):
    def test_worst_of_empty_is_pass(self):
        self.assertIs(Status.worst([]), Status.PASS)

    def test_worst_picks_highest_severity(self):
        self.assertIs(
            Status.worst([Status.PASS, Status.ESCALATE, Status.REPAIR]), Status.ESCALATE
        )


class TestFinding(unittest.TestCase):
    def test_lexical_finding_may_not_block(self):
        with self.assertRaises(ValueError):
            finding(status=Status.BLOCK, confidence=Confidence.LEXICAL)

    def test_unresolved_finding_may_not_block(self):
        """Generated code we could not see means the verdict is a guess."""
        with self.assertRaises(ValueError):
            finding(status=Status.BLOCK, confidence=Confidence.UNRESOLVED)

    def test_unresolved_finding_may_still_advise(self):
        self.assertIsNotNone(finding(status=Status.REPAIR, confidence=Confidence.UNRESOLVED))

    def test_only_exact_analysis_may_block(self):
        self.assertTrue(Confidence.EXACT.may_block)
        self.assertFalse(Confidence.LEXICAL.may_block)
        self.assertFalse(Confidence.UNRESOLVED.may_block)

    def test_lexical_finding_may_repair(self):
        self.assertIsNotNone(finding(status=Status.REPAIR, confidence=Confidence.LEXICAL))

    def test_negative_line_is_rejected(self):
        with self.assertRaises(ValueError):
            finding(line=-1)


class TestVerdict(unittest.TestCase):
    def test_empty_verdict_passes_and_is_truthy(self):
        verdict = Verdict.of([])
        self.assertIs(verdict.status, Status.PASS)
        self.assertTrue(verdict)

    def test_status_is_the_most_severe_finding(self):
        verdict = Verdict.of([finding(status=Status.REPAIR), finding(status=Status.ESCALATE, line=9)])
        self.assertIs(verdict.status, Status.ESCALATE)
        self.assertFalse(verdict)

    def test_findings_are_ordered_deterministically(self):
        unordered = [
            finding(file="b.py", line=2),
            finding(file="a.py", line=9),
            finding(file="a.py", line=1),
        ]
        keys = [(f.file, f.line) for f in Verdict.of(unordered).findings]
        self.assertEqual(keys, [("a.py", 1), ("a.py", 9), ("b.py", 2)])

    def test_same_findings_in_any_order_serialise_identically(self):
        a = Verdict.of([finding(file="b.py"), finding(file="a.py")])
        b = Verdict.of([finding(file="a.py"), finding(file="b.py")])
        self.assertEqual(a.to_json(), b.to_json())

    def test_checked_and_skipped_are_recorded(self):
        verdict = Verdict.of([], checked=["b.py", "a.py"], skipped=["c.ts"])
        self.assertEqual(verdict.checked, ("a.py", "b.py"))
        self.assertEqual(verdict.skipped, ("c.ts",))

    def test_demote_caps_severity(self):
        verdict = Verdict.of([finding(status=Status.ESCALATE)]).demote(Status.REPAIR)
        self.assertIs(verdict.status, Status.REPAIR)

    def test_demote_does_not_raise_low_severity(self):
        verdict = Verdict.of([finding(status=Status.REPAIR)]).demote(Status.BLOCK)
        self.assertIs(verdict.status, Status.REPAIR)

    def test_merge_combines_and_reorders(self):
        merged = Verdict.of([finding(file="b.py")]).merge(Verdict.of([finding(file="a.py")]))
        self.assertEqual([f.file for f in merged.findings], ["a.py", "b.py"])

    def test_prescription_names_location_and_remedy(self):
        text = Verdict.of([finding()]).prescription
        self.assertIn("tests/test_invoice.py:41", text)
        self.assertIn("Restore an equality assertion.", text)

    def test_json_roundtrip_is_lossless(self):
        verdict = Verdict.of(
            [finding(before="assert x == 3", after="assert x", symbol="test_total")],
            checked=["tests/test_invoice.py"],
        )
        self.assertEqual(Verdict.from_dict(json.loads(verdict.to_json())), verdict)

    def test_schema_version_is_emitted(self):
        self.assertEqual(json.loads(Verdict.of([]).to_json())["schema_version"], SCHEMA_VERSION)

    def test_unknown_schema_version_is_refused(self):
        with self.assertRaises(ValueError):
            Verdict.from_dict({"schema_version": SCHEMA_VERSION + 1, "findings": []})




class TestSchemaContract(unittest.TestCase):
    """The one place the schema version is pinned to a literal.

    Surface tests assert they emit ``SCHEMA_VERSION``; this asserts what that
    number currently is. Changing it here is the deliberate act of declaring a
    breaking change to the cross-language verdict shape, and should come with a
    CHANGELOG entry.
    """

    def test_schema_version_is_pinned(self):
        self.assertEqual(SCHEMA_VERSION, 3)


if __name__ == "__main__":
    unittest.main()