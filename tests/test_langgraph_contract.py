"""Shared binding contract fixtures.

Other SDKs consume these inputs and expected public state values. Python is the
only producer of rule verdicts; bindings must compare against this contract,
not recreate rules in their own test suites.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from yieldpoint.langgraph import make_router, verify_node


FIXTURES = Path(__file__).parent / "fixtures" / "langgraph_contract"


class TestLangGraphContract(unittest.TestCase):
    def test_public_state_contract_fixtures(self) -> None:
        for path in sorted(FIXTURES.glob("*.json")):
            with self.subTest(fixture=path.name):
                fixture = json.loads(path.read_text(encoding="utf-8"))
                state = dict(fixture["state"])
                update = verify_node()(state)
                state.update(update)
                expected = fixture["expected"]
                self.assertEqual(state["verdict"]["status"], expected["status"])
                self.assertEqual(make_router()(state), expected["route"])
                self.assertEqual(state["yieldpoint_attempts"], expected["attempts"])
                self.assertEqual(state["yieldpoint_loop_tripped"], expected["loop_tripped"])
                if "skipped" in expected:
                    self.assertEqual(state["verdict"]["skipped"], expected["skipped"])

