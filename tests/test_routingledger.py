"""Routing accounting is local, redacted, and outside verification totals."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from yieldpoint.core.policy import Policy
from yieldpoint.harness import Change, admit, build_profile
from yieldpoint.routingledger import RoutingFact, path_for_routing, record, summarise


class TestRoutingLedger(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.policy = Policy()
        self.profile = build_profile(Change("src/demo.py", "x = 1\n", "x = 2\n")).to_dict()
        self.session = admit(self.profile, task_id="task-1", selected_model="private-model").to_dict()

    def tearDown(self):
        self.tmp.cleanup()

    def test_records_only_operational_metadata(self):
        with patch("yieldpoint.routingledger.enabled", return_value=True):
            self.assertTrue(record(RoutingFact("admission", self.profile, self.session),
                                   policy=self.policy, root=self.root))
            self.assertTrue(record(RoutingFact("handoff", self.profile, self.session,
                                               allowed=False, event="verification_failed"),
                                   policy=self.policy, root=self.root))
        raw = path_for_routing(self.policy, self.root).read_text()
        self.assertNotIn("private-model", raw)
        self.assertNotIn("src/demo.py", raw)
        self.assertEqual(summarise(self.policy, self.root)["handoffs_denied"], 1)

    def test_metrics_opt_out_writes_nothing(self):
        policy = Policy.load({"metrics": {"enabled": False}})
        self.assertIs(record(RoutingFact("profile", self.profile), policy=policy, root=self.root), False)
        self.assertFalse(path_for_routing(policy, self.root).exists())


if __name__ == "__main__":
    unittest.main()
