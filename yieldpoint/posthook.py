"""PostToolUse compaction: shrink tool output before the model reads it.

The MCP tool this supersedes could never save anything. To call
``yieldpoint_compact`` with a tool's output, an agent must already be holding
that output in its prompt — the context was spent before the call was made,
and the call itself then cost more. This hook runs in the only place where the
saving is still available: after the tool returns and before the model is
shown the result.

Nothing here summarises, truncates or reorders. The payload is parsed to prove
it is JSON, then insignificant whitespace is removed and nothing else. On this
repository's own JSON payloads that is 13-41% of the bytes.

Anything that is not a JSON string passes through untouched. A compactor that
guesses at a shape it does not understand is how content goes missing.
"""

from __future__ import annotations

import json
import sys

from .contextrecording import compact_and_record

EVENT = "PostToolUse"


def _output(payload: dict) -> str | None:
    """The tool result, if it is a string we can safely rewrite.

    A structured response is left alone. Re-serialising a dict would change a
    shape the runtime validates, and the bytes saved are not worth guessing.
    """
    response = payload.get("tool_response")
    return response if isinstance(response, str) else None


def replacement(payload: dict, *, root: str = ".", policy=None) -> dict | None:
    """The hook's reply, or ``None`` when the output is better left alone."""
    text = _output(payload)
    if not text:
        return None
    try:
        result, _ = compact_and_record(text, root=root, policy=policy)
    except ValueError:
        return None          # not JSON; nothing this hook understands
    if result.output_chars >= result.input_chars:
        return None          # no gain, so no rewrite and no claim of one
    return {"hookSpecificOutput": {"hookEventName": EVENT,
                                   "updatedToolOutput": result.text}}


def post_command(args) -> int:
    """Read one PostToolUse payload and reply, staying silent when unsure.

    Every failure path is a pass-through. A hook that errors on an unexpected
    payload would break every tool call in the session, which is a far worse
    outcome than forwarding some whitespace.
    """
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    if not isinstance(payload, dict):
        return 0
    reply = replacement(payload, root=getattr(args, "root", ".") or ".",
                        policy=getattr(args, "policy", None))
    if reply:
        print(json.dumps(reply))
    return 0


__all__ = ["EVENT", "post_command", "replacement"]
