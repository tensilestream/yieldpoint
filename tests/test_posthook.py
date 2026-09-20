"""Compacting tool output before the model reads it.

Every path that is not clearly safe must forward the output untouched. A hook
that raises breaks every tool call in the session, and a hook that guesses at
a shape it does not understand loses content silently — which is the failure
this project exists to report, committed by the tool itself.
"""

from __future__ import annotations

import json
import unittest

from yieldpoint.posthook import EVENT, replacement

POLICY = {"metrics": {"enabled": False}}


def replaced(payload: dict) -> str | None:
    reply = replacement(payload, policy=POLICY)
    return reply["hookSpecificOutput"]["updatedToolOutput"] if reply else None


class ReplacementCase(unittest.TestCase):
    def test_removes_only_insignificant_whitespace(self):
        text = json.dumps({"a": [1, 2], "b": "keep  me"}, indent=4)
        out = replaced({"tool_response": text})
        self.assertEqual(out, '{"a":[1,2],"b":"keep  me"}')
        self.assertEqual(json.loads(out), json.loads(text))

    def test_names_the_event_the_runtime_expects(self):
        reply = replacement({"tool_response": '[ 1 ]'}, policy=POLICY)
        self.assertEqual(reply["hookSpecificOutput"]["hookEventName"], EVENT)
        self.assertEqual(EVENT, "PostToolUse")

    def test_already_compact_output_is_left_alone(self):
        """No gain means no rewrite, so nothing claims a saving it did not make."""
        self.assertIsNone(replaced({"tool_response": '[1,2]'}))

    def test_text_that_is_not_json_passes_through(self):
        self.assertIsNone(replaced({"tool_response": "error: build failed"}))

    def test_a_structured_response_is_not_reshaped(self):
        """Re-serialising a dict would change a shape the runtime validates."""
        self.assertIsNone(replaced({"tool_response": {"success": True}}))

    def test_a_payload_with_no_output_is_ignored(self):
        self.assertIsNone(replaced({}))
        self.assertIsNone(replaced({"tool_response": ""}))

    def test_strings_are_preserved_byte_for_byte(self):
        text = json.dumps({"detail": "line one\nline  two\t— em dash"})
        self.assertEqual(json.loads(replaced({"tool_response": text}) or text),
                         json.loads(text))


if __name__ == "__main__":
    unittest.main()


class BoundedRoutingCase(unittest.TestCase):
    """Which adapter runs is decided by the tool's name, never by the content."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        from yieldpoint.core.policy import Policy
        self.root = Path(tempfile.mkdtemp())
        self.policy = Policy.from_dict({"metrics": {"enabled": False}})
        self.long = "\n".join(f"src/f{i}.py:{i}: match" for i in range(400))

    def _out(self, tool: str, text: str):
        reply = replacement({"tool_name": tool, "tool_response": text},
                            root=str(self.root), policy=self.policy)
        return reply["hookSpecificOutput"]["updatedToolOutput"] if reply else None

    def test_search_output_is_bounded_and_declares_the_omission(self):
        out = self._out("Grep", self.long)
        self.assertLess(len(out), len(self.long))
        self.assertIn("not shown", out.splitlines()[-1])

    def test_an_unknown_tool_passes_through_untouched(self):
        """Guessing that a blob looks like search output loses the wrong lines."""
        self.assertIsNone(self._out("SomeOtherTool", self.long))

    def test_a_short_result_is_not_bounded(self):
        self.assertIsNone(self._out("Grep", "one\ntwo\nthree"))

    def test_json_takes_the_lossless_path_whatever_tool_produced_it(self):
        import json
        text = json.dumps({"a": [1, 2]}, indent=2)
        self.assertEqual(self._out("Grep", text), '{"a":[1,2]}')

    def test_no_handle_is_offered_when_retention_is_off(self):
        out = self._out("Grep", self.long)
        self.assertIn("not shown", out)
        self.assertNotIn("recall", out)
