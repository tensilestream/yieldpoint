"""Yieldpoint as a function tool for the OpenAI Agents SDK.

A tool the model chooses to call is **advice**, not a gate — an agent set on
weakening a test will not ask permission. Give it the tool so a blocked agent
can find out why for free, and put the gate somewhere it has no vote: the
`verify_before_apply` wrapper below, CI, or a commit hook.
"""

from __future__ import annotations

import json

from yieldpoint.core.verdict import Status
from yieldpoint.verify import verify_change, verify_diff

POLICY = ".yieldpoint.json"


# --------------------------------------------------------- advisory: the tool

def yieldpoint_verify(path: str, before: str, after: str) -> str:
    """Check whether a proposed edit weakens what the tests verify.

    Register with ``@function_tool`` (or pass the schema by hand). The
    docstring is what the model reads, so it says when to call it.
    """
    verdict = verify_change(before, after, path, POLICY)
    return json.dumps(verdict.to_dict(), indent=2)


def as_tool():
    """Wrap it for the SDK. Kept separate so this file imports without it."""
    from agents import function_tool

    return function_tool(yieldpoint_verify)


# ------------------------------------------------------- enforcing: the gate

class Rejected(Exception):
    """The change was not applied."""


def verify_before_apply(path: str, before: str, after: str, apply) -> str:
    """Wrap whatever actually writes the file.

    This is the part that enforces. The agent can decline to call the tool
    above; it cannot decline to go through the function that writes to disk.
    """
    verdict = verify_change(before, after, path, POLICY)
    if verdict.status in (Status.PASS, Status.UNVERIFIED):
        return apply(after)
    raise Rejected(verdict.prescription)


def review_session(diff_text: str, root: str = ".") -> str:
    """One call at the end of a run: everything the agent changed."""
    return verify_diff(diff_text, root, POLICY).prescription or "clean"
