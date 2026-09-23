"""The routing MCP tools, kept separate from the protocol and client tests.

They share nothing with those beyond the call harness, and a single file holding
both had more than one reason to change.
"""

import json
import unittest

from yieldpoint.core.policy import Policy
from yieldpoint.mcp.server import handle

POLICY = Policy()


def request(method, params=None, identifier=1):
    message = {"jsonrpc": "2.0", "method": method, "id": identifier}
    if params is not None:
        message["params"] = params
    return handle(json.dumps(message), POLICY)


class TestRoutingTools(unittest.TestCase):
    def call(self, name, arguments):
        return request("tools/call", {"name": name, "arguments": arguments})["result"]

    def test_routing_profile_is_advisory_and_marks_unknown_coverage(self):
        result = self.call("yieldpoint_routing_profile", {
            "path": "src/widget.ts", "after": "export const x = 1\n",
        })
        self.assertFalse(result["isError"])
        profile = result["structuredContent"]
        self.assertFalse(profile["coverage"]["exact_analysis"])
        self.assertIn("host-owned", result["content"][0]["text"])

    def test_handoff_tools_preserve_the_profile_session_pair(self):
        profile = self.call("yieldpoint_routing_profile", {
            "path": "src/widget.py", "after": "x = 1\n",
            "verdict": {"status": "repair", "findings": [{"rule": "boundary_violation"}]},
        })["structuredContent"]
        from yieldpoint.harness import admit
        session = admit(profile, task_id="mcp-test").to_dict()
        self.assertTrue(self._handoff(profile, "mcp-test")["allowed"])
        capsule = self.call("yieldpoint_build_task_capsule", {
            "session": session, "profile": profile, "objective": "Fix widget",
        })["structuredContent"]
        self.assertEqual(capsule["profile_id"], profile["profile_id"])

    def test_an_unverified_change_is_not_handed_off_through_mcp(self):
        profile = self.call("yieldpoint_routing_profile", {
            "path": "src/widget.py", "after": "x = 1\n"})["structuredContent"]
        checked = self._handoff(profile, "mcp-unverified")
        self.assertFalse(checked["allowed"])
        self.assertIn("unverified", checked["reason"])

    def _handoff(self, profile, task_id):
        from yieldpoint.harness import admit
        return self.call("yieldpoint_handoff_check", {
            "session": admit(profile, task_id=task_id).to_dict(), "profile": profile,
            "event": "verification_failed",
            "candidate_capabilities": ["code_generation", "tool_use", "strong_reasoning"],
        })["structuredContent"]


if __name__ == "__main__":
    unittest.main()
