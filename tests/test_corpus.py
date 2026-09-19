"""The corpus is a gate, not a report.

PLAN_AND_POSITIONING.md section 7 makes a measured false-positive rate the
condition a rule must meet before it may block. Asserting the rate here is what
stops that number drifting quietly: a change that starts flagging a legitimate
refactor fails CI rather than showing up as a complaint months later.
"""

from __future__ import annotations

import unittest

from tests.corpus import LEGITIMATE, TAMPERING
from tests.corpus.case import HOLDOUT
from tests.corpus.measure import evaluate, score


class TestCorpusRates(unittest.TestCase):
    def test_no_legitimate_refactor_is_reported(self):
        offenders = [
            f"{r.case.name} -> {', '.join(r.rules)}"
            for r in map(evaluate, LEGITIMATE) if r.fired
        ]
        self.assertEqual(offenders, [], "false positives on legitimate refactors")

    def test_every_tampering_pattern_is_reported(self):
        missed = [r.case.name for r in map(evaluate, TAMPERING) if not r.fired]
        self.assertEqual(missed, [], "tampering not detected")

    def test_the_held_out_split_is_not_empty(self):
        """A held-out score is only evidence if something is actually held out."""
        _fps, _fns, legit, tamper = score(HOLDOUT)
        self.assertGreaterEqual(legit, 5)
        self.assertGreaterEqual(tamper, 5)

    def test_cases_are_uniquely_named(self):
        names = [c.name for c in (*LEGITIMATE, *TAMPERING)]
        self.assertEqual(len(names), len(set(names)))


if __name__ == "__main__":
    unittest.main()
