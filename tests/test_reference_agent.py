"""The LangGraph reference track only adapts Qwen's broken call transport."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = (str(ROOT / "benchmarks" / "harness"),
                str(ROOT / "benchmarks" / "ollama"), str(ROOT))

from langchain_core.messages import AIMessage  # noqa: E402
from langgraph_agent import AgentRuntime, AgentSettings  # noqa: E402
from reference_agent import lift_text_tool_calls  # noqa: E402
from yieldpoint.core.verdict import Status, Verdict  # noqa: E402


NAMES = frozenset({"read_file", "write_file"})


class TestTextToolCalls(unittest.TestCase):
    def test_lifts_nested_write_arguments_without_losing_metadata(self):
        payload = {"name": "write_file", "arguments": {
            "path": "src/example.py", "content": "return {'nested': 1}\n"}}
        reply = AIMessage(content=json.dumps(payload), response_metadata={"model": "qwen"})

        lifted = lift_text_tool_calls(reply, NAMES)

        self.assertEqual(lifted.tool_calls[0]["name"], "write_file")
        self.assertEqual(lifted.tool_calls[0]["args"], payload["arguments"])
        self.assertEqual(lifted.response_metadata, {"model": "qwen"})

    def test_leaves_native_structured_calls_alone(self):
        reply = AIMessage(content="", tool_calls=[{
            "name": "read_file", "args": {"path": "x.py"}, "id": "native"}])

        self.assertIs(lift_text_tool_calls(reply, NAMES), reply)

    def test_leaves_prose_alone(self):
        reply = AIMessage(content="I need to inspect the failing test first.")

        self.assertIs(lift_text_tool_calls(reply, NAMES), reply)

    def test_refuses_an_unknown_tool_name(self):
        reply = AIMessage(content=json.dumps({"name": "shell", "arguments": {"cmd": "pwd"}}))

        self.assertIs(lift_text_tool_calls(reply, NAMES), reply)

    def test_primary_harness_continues_unknown_but_stops_blocked_verdicts(self):
        runtime = AgentRuntime(AgentSettings("model", ".", "true", True, 5))
        unknown = {"verdict": _verdict(Status.UNVERIFIED).to_dict()}
        blocked = {"verdict": _verdict(Status.BLOCK).to_dict()}

        self.assertEqual(runtime.after_verify(unknown), "agent")
        self.assertEqual(runtime.after_verify(blocked), "end")


def _verdict(status: Status) -> Verdict:
    if status is Status.UNVERIFIED:
        return Verdict.of([], skipped=["not analysable"])
    from yieldpoint.core.verdict import Finding

    return Verdict.of([Finding("rule", status, "tests/example.py", 1,
                               "blocked", "repair it")])


if __name__ == "__main__":
    unittest.main()
