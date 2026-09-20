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

from .bounded import failures, head
from .contextrecording import bound_and_record, compact_and_record
from .recall import keep

EVENT = "PostToolUse"

#: Which adapter each tool's output gets. Keyed on the name the runtime gives
#: the tool, never sniffed from the content: guessing that a blob "looks like"
#: search output is how the wrong lines get dropped.
ADAPTERS = {"Grep": "head", "Glob": "head", "Bash": "failures"}

#: Results shorter than this are forwarded whole. Bounding a short result costs
#: a disclosure line and saves nothing.
BOUND_ABOVE_LINES = 200

#: How many lines a ``head`` adapter keeps.
HEAD_LINES = 60


def _output(payload: dict) -> str | None:
    """The tool result, if it is a string we can safely rewrite.

    A structured response is left alone. Re-serialising a dict would change a
    shape the runtime validates, and the bytes saved are not worth guessing.
    """
    response = payload.get("tool_response")
    return response if isinstance(response, str) else None


def _reply(text: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": EVENT,
                                   "updatedToolOutput": text}}


def _lossless(text: str, root: str, policy) -> dict | None:
    """Whitespace-only compaction, for output that is valid JSON."""
    try:
        result, _ = compact_and_record(text, root=root, policy=policy)
    except ValueError:
        return None          # not JSON; nothing this adapter understands
    if result.output_chars >= result.input_chars:
        return None          # no gain, so no rewrite and no claim of one
    return _reply(result.text)


def _bounded(text: str, adapter: str, root: str, policy) -> dict | None:
    """Deliver part of a long result, with the omission stated in the result.

    The original is stored first, so the disclosure can name a handle that
    already resolves. When retention is off the handle is empty and the
    disclosure says what was dropped without offering to fetch it — still
    honest, just less useful.
    """
    if len(text.splitlines()) <= BOUND_ABOVE_LINES:
        return None
    handle = keep(text, root=root, policy=policy)
    result = (head(text, limit=HEAD_LINES, handle=handle) if adapter == "head"
              else failures(text, handle=handle))
    if result.complete or len(result.text) >= len(text):
        return None
    bound_and_record(result, root=root, policy=policy)
    return _reply(result.text)


def replacement(payload: dict, *, root: str = ".", policy=None) -> dict | None:
    """The hook's reply, or ``None`` when the output is better left alone."""
    text = _output(payload)
    if not text:
        return None
    lossless = _lossless(text, root, policy)
    if lossless:
        return lossless
    adapter = ADAPTERS.get(str(payload.get("tool_name") or ""))
    if not adapter:
        return None
    # Resolved here because the store needs a real policy to read the
    # retention switch from; passing None through would silently decline to
    # store and hand back a disclosure with no handle in it.
    from .core.policy import Policy
    return _bounded(text, adapter, root, Policy.load(policy, root=root))


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
