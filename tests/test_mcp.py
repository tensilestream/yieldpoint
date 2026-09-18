"""MCP server and editor configuration.

Two properties matter more than the feature set: stdout carries protocol and
nothing else, and no single bad message ends the session. An editor integration
that dies on one malformed request is worse than none.
"""

import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from aegisflow.core.policy import Policy
from aegisflow.mcp.clients import BY_KEY, CLIENTS, config_path, install, snippet
from aegisflow.mcp.server import METHOD_NOT_FOUND, PARSE_ERROR, handle, serve
from aegisflow.mcp.tools import TOOLS, call

POLICY = Policy()

WEAKENED = {
    "path": "tests/test_invoice.py",
    "before": "def test_total(inv):\n    assert inv.total == 42\n",
    "after": "def test_total(inv):\n    assert inv.total is not None\n",
}


def request(method, params=None, identifier=1):
    message = {"jsonrpc": "2.0", "method": method}
    if identifier is not None:
        message["id"] = identifier
    if params is not None:
        message["params"] = params
    return handle(json.dumps(message), POLICY)


class TestHandshake(unittest.TestCase):
    def test_initialize_reports_the_server(self):
        result = request("initialize", {"protocolVersion": "2024-11-05"})["result"]
        self.assertEqual(result["serverInfo"]["name"], "aegisflow")
        self.assertIn("tools", result["capabilities"])

    def test_the_clients_protocol_version_is_echoed(self):
        result = request("initialize", {"protocolVersion": "2025-06-18"})["result"]
        self.assertEqual(result["protocolVersion"], "2025-06-18")

    def test_a_nonsense_version_falls_back_to_ours(self):
        result = request("initialize", {"protocolVersion": "banana"})["result"]
        self.assertEqual(result["protocolVersion"], "2024-11-05")

    def test_instructions_tell_the_agent_when_to_call(self):
        result = request("initialize", {})["result"]
        self.assertIn("aegis_verify_change", result["instructions"])

    def test_ping(self):
        self.assertEqual(request("ping")["result"], {})


class TestToolListing(unittest.TestCase):
    def test_every_tool_is_offered(self):
        names = {tool["name"] for tool in request("tools/list")["result"]["tools"]}
        self.assertEqual(names, {
            "aegis_verify_change", "aegis_verify_diff", "aegis_scan", "aegis_policy"})

    def test_schemas_are_well_formed(self):
        for tool in TOOLS:
            self.assertEqual(tool["inputSchema"]["type"], "object", tool["name"])
            self.assertTrue(tool["description"], tool["name"])
            for required in tool["inputSchema"].get("required", []):
                self.assertIn(required, tool["inputSchema"]["properties"], tool["name"])


class TestToolCalls(unittest.TestCase):
    def call(self, name, arguments):
        return request("tools/call", {"name": name, "arguments": arguments})["result"]

    def test_verify_change_reports_a_weakening(self):
        result = self.call("aegis_verify_change", WEAKENED)
        self.assertFalse(result["isError"])
        self.assertIn("assertion_monotonicity", result["content"][0]["text"])
        self.assertEqual(result["structuredContent"]["status"], "repair")

    def test_structured_content_is_the_versioned_verdict(self):
        result = self.call("aegis_verify_change", WEAKENED)
        self.assertEqual(result["structuredContent"]["schema_version"], 1)

    def test_a_clean_change_passes(self):
        result = self.call("aegis_verify_change",
                           {"path": "tests/t.py", "before": WEAKENED["before"],
                            "after": WEAKENED["before"]})
        self.assertEqual(result["structuredContent"]["status"], "pass")

    def test_verify_diff(self):
        diff = ("--- a/tests/t.py\n+++ b/tests/t.py\n@@ -1,2 +1,2 @@\n"
                " def test_total(inv):\n-    assert inv.total == 42\n"
                "+    assert inv.total is not None\n")
        result = self.call("aegis_verify_diff", {"diff": diff, "root": "/nonexistent"})
        self.assertFalse(result["isError"])

    def test_policy_lists_the_rules_in_force(self):
        result = self.call("aegis_policy", {})
        self.assertIn("assertion_monotonicity", result["structuredContent"]["rules"])

    def test_scan_audits_a_directory(self):
        result = self.call("aegis_scan", {"path": "aegisflow"})
        self.assertIn("file(s) audited", result["content"][0]["text"])

    def test_an_unknown_tool_is_an_error_not_a_crash(self):
        result = self.call("aegis_nonsense", {})
        self.assertTrue(result["isError"])

    def test_a_failing_tool_returns_an_error_result(self):
        text, _, is_error = call("aegis_verify_change", {"after": None, "path": None}, POLICY)
        self.assertTrue(is_error or text)


class TestResilience(unittest.TestCase):
    """No single bad message may end the session."""

    def test_malformed_json(self):
        response = handle("{not json", POLICY)
        self.assertEqual(response["error"]["code"], PARSE_ERROR)

    def test_a_non_object_request(self):
        self.assertIsNotNone(handle("[1, 2, 3]", POLICY)["error"])

    def test_unknown_method(self):
        self.assertEqual(request("nonsense/method")["error"]["code"], METHOD_NOT_FOUND)

    def test_a_notification_gets_no_reply(self):
        self.assertIsNone(request("notifications/initialized", identifier=None))

    def test_optional_capabilities_return_empty_rather_than_failing(self):
        self.assertEqual(request("resources/list")["result"], {"resources": []})
        self.assertEqual(request("prompts/list")["result"], {"prompts": []})

    def test_the_loop_survives_a_bad_message_in_the_middle(self):
        lines = [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}),
            "{ broken",
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
        ]
        out = io.StringIO()
        serve(io.StringIO("\n".join(lines) + "\n"), out, POLICY)
        responses = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual(len(responses), 3)
        self.assertIn("tools", responses[-1]["result"])

    def test_stdout_carries_only_protocol(self):
        """A stray print corrupts the stream and disconnects the client."""
        out = io.StringIO()
        message = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                              "params": {"name": "aegis_verify_change", "arguments": WEAKENED}})
        serve(io.StringIO(message + "\n"), out, POLICY)
        for line in out.getvalue().splitlines():
            json.loads(line)  # raises if anything non-protocol was written

    def test_blank_lines_are_ignored(self):
        out = io.StringIO()
        serve(io.StringIO('\n\n{"jsonrpc":"2.0","id":1,"method":"ping"}\n\n'), out, POLICY)
        self.assertEqual(len(out.getvalue().splitlines()), 1)


class TestClients(unittest.TestCase):
    def test_every_client_resolves_a_path(self):
        for client in CLIENTS:
            self.assertTrue(str(config_path(client)).endswith(".json"), client.key)

    def test_vscode_uses_its_own_shape(self):
        parsed = json.loads(snippet(BY_KEY["vscode"]))
        self.assertIn("servers", parsed)
        self.assertEqual(parsed["servers"]["aegisflow"]["type"], "stdio")

    def test_zed_nests_the_command(self):
        parsed = json.loads(snippet(BY_KEY["zed"]))
        self.assertEqual(parsed["context_servers"]["aegisflow"]["command"]["path"], "aegisflow")

    def test_the_common_shape_is_mcp_servers(self):
        for key in ("claude-code", "claude-desktop", "cursor", "windsurf"):
            self.assertIn("mcpServers", json.loads(snippet(BY_KEY[key])), key)


class TestInstalling(unittest.TestCase):
    def setUp(self):
        self._previous = Path.cwd()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        os.chdir(self.root)

    def tearDown(self):
        os.chdir(self._previous)
        self._tmp.cleanup()

    def test_writing_a_project_config(self):
        path, backup = install(BY_KEY["claude-code"], self.root)
        self.assertIsNone(backup)
        written = json.loads(path.read_text())
        self.assertEqual(written["mcpServers"]["aegisflow"]["command"], "aegisflow")

    def test_existing_configuration_is_preserved_and_backed_up(self):
        path = self.root / ".mcp.json"
        path.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}, "keep": 1}))
        _, backup = install(BY_KEY["claude-code"], self.root)
        written = json.loads(path.read_text())
        self.assertEqual(written["keep"], 1)
        self.assertIn("other", written["mcpServers"])
        self.assertIsNotNone(backup)
        self.assertTrue(backup.is_file())

    def test_reinstalling_does_not_duplicate(self):
        install(BY_KEY["claude-code"], self.root)
        path, _ = install(BY_KEY["claude-code"], self.root)
        self.assertEqual(len(json.loads(path.read_text())["mcpServers"]), 1)

    def test_unparseable_configuration_is_backed_up_before_replacement(self):
        path = self.root / ".mcp.json"
        path.write_text("{ not json")
        _, backup = install(BY_KEY["claude-code"], self.root)
        self.assertEqual(backup.read_text(), "{ not json")
        self.assertIn("aegisflow", json.loads(path.read_text())["mcpServers"])


if __name__ == "__main__":
    unittest.main()
