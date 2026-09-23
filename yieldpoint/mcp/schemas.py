"""The tool descriptions the MCP client sees.

Separated from tools.py because the two change for different reasons:
this file when there is a new capability to offer, that one when there is
a better way to compute an answer. It also keeps both inside the length
limit this project enforces on everyone else.
"""

from __future__ import annotations

from typing import Any

_FILE = {"type": "string", "description": "Repository-relative path being changed."}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "yieldpoint_verify_change",
        "title": "Verify a proposed edit",
        "description": (
            "Check a proposed file edit before writing it. Returns a verdict of pass, "
            "repair, escalate or block, plus a prescription naming exactly what to fix. "
            "Call this before editing any test file."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": _FILE,
                "before": {"type": "string", "description": "Current content, omit if new."},
                "after": {"type": "string", "description": "Proposed content."},
            },
            "required": ["path", "after"],
        },
    },
    {
        "name": "yieldpoint_verify_diff",
        "title": "Verify a change set",
        "description": (
            "Check a unified diff across many files. Subjects are pooled across the "
            "change set, so moving a test between files is not reported as a loss."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "diff": {"type": "string", "description": "Unified diff text."},
                "root": {"type": "string", "description": "Directory the paths are relative to."},
            },
            "required": ["diff"],
        },
    },
    {
        "name": "yieldpoint_review",
        "title": "Check uncommitted work",
        "description": (
            "Verify everything changed but not yet committed, reading the diff from "
            "git. Takes no arguments. Call this after finishing a set of edits, and "
            "before telling the user the work is done — it is the cheapest way to "
            "find out whether the change weakened the test suite."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string", "description": "Repository directory."},
                "staged": {"type": "boolean", "description": "Only what is staged."},
                "against": {
                    "type": "string",
                    "description": "Compare with a branch or commit instead of the working tree.",
                },
            },
        },
    },
    {
        "name": "yieldpoint_scan",
        "title": "Audit a repository",
        "description": (
            "Report the current state of a repository rather than the effect of a "
            "change. Rules that are differential when verifying an edit run absolutely."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Directory to audit."}},
        },
    },
    {
        "name": "yieldpoint_assess",
        "title": "How risky is this change, and how much model does it need",
        "description": (
            "Classify a proposed edit before doing it: a risk level, the amount of "
            "model the work needs, and the measured signals behind both. Computed "
            "from the syntax tree, so it costs nothing and answers the same way "
            "every time. Use it to decide whether to escalate or to keep going."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": _FILE,
                "before": {"type": "string", "description": "Current content, omit if new."},
                "after": {"type": "string", "description": "Proposed content."},
                "task": {"type": "string", "description": "What you were asked to do."},
            },
            "required": ["path", "after"],
        },
    },
    {
        "name": "yieldpoint_routing_profile",
        "title": "Build a provider-neutral routing profile",
        "description": (
            "Describe the measured risk, verification coverage, required checks, "
            "and safe handoff limits for one proposed change. It never selects a "
            "model or contacts a provider; the host owns both decisions."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": _FILE,
                "before": {"type": "string", "description": "Current content, omit if new."},
                "after": {"type": "string", "description": "Proposed content."},
                "task": {"type": "string", "description": "Host objective, retained only locally."},
            },
            "required": ["path", "after"],
        },
    },
    {
        "name": "yieldpoint_stats",
        "title": "What Yieldpoint has caught and what it cost",
        "description": (
            "Report the local ledger: how many verifications ran, what they caught, "
            "and what the critique cost. Figures are separated into measured, "
            "architectural and estimated, and none is transmitted anywhere."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"root": {"type": "string", "description": "Project directory."}},
        },
    },
    {
        "name": "yieldpoint_brief",
        "title": "What to know before editing",
        "description": (
            "Given the files a task is about to touch, report what is already "
            "true about them: how many lines of headroom remain, which "
            "functions are at their limit, which assertions must not get "
            "weaker, and which imports the file's zone forbids. Call this "
            "before writing code, not after — a rejected edit costs another "
            "turn, and everything here was knowable in advance."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Files the task will create or change.",
                },
            },
            "required": ["paths"],
        },
    },
    {
        "name": "yieldpoint_policy",
        "title": "Show the active rules",
        "description": (
            "List the rules in force and their severities, so work can be planned "
            "within them rather than discovered by rejection."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
]


__all__ = ["TOOLS"]
