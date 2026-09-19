"""What AegisFlow offers over MCP.

Deliberately small. An MCP tool is **advisory**: the agent decides whether to
call it, so an agent intent on weakening a test will simply not ask. That is not
a flaw to be papered over — it is why `aegisflow hook` exists, and why the
LangGraph node sits on the graph edge where the agent cannot route around it.

What MCP is genuinely good at is the other half: **explanation**. A blocked agent
otherwise burns tokens guessing why. These tools let it ask directly, and get a
deterministic answer for free.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from ..core.policy import Policy
from ..core.verdict import Verdict
from ..verify import verify_change, verify_diff

_FILE = {"type": "string", "description": "Repository-relative path being changed."}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "aegis_verify_change",
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
        "name": "aegis_verify_diff",
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
        "name": "aegis_review",
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
        "name": "aegis_scan",
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
        "name": "aegis_policy",
        "title": "Show the active rules",
        "description": (
            "List the rules in force and their severities, so work can be planned "
            "within them rather than discovered by rejection."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def call(name: str, arguments: dict[str, Any], policy: Policy) -> tuple[str, dict, bool]:
    """Run one tool. Returns (text, structured, is_error) and never raises."""
    handler = _HANDLERS.get(name)
    if handler is None:
        return f"Unknown tool: {name}", {}, True
    try:
        return handler(arguments or {}, policy)
    except Exception as exc:  # a tool error must not take the server down
        return f"{name} failed: {exc}", {}, True


def _verify_change(arguments: dict, policy: Policy):
    verdict = verify_change(
        arguments.get("before"), arguments.get("after"), arguments.get("path", ""), policy
    )
    return _render(verdict), verdict.to_dict(), False


def _verify_diff(arguments: dict, policy: Policy):
    verdict = verify_diff(arguments.get("diff", ""), arguments.get("root") or ".", policy)
    return _render(verdict), verdict.to_dict(), False


def _review(arguments: dict, policy: Policy):
    from ..worktree import uncommitted

    diff = uncommitted(
        arguments.get("root") or ".",
        staged=bool(arguments.get("staged")),
        against=arguments.get("against") or "",
    )
    if not diff.ok:
        # Not an error: "nothing to check" and "not a git repository" are both
        # ordinary answers, and returning is_error would make the agent retry.
        return diff.reason, {"status": "unverified", "reason": diff.reason}, False

    verdict = verify_diff(diff.text, root=diff.root, policy=policy)
    return _render(verdict), verdict.to_dict(), False


def _scan(arguments: dict, policy: Policy):
    from ..scan import scan

    result = scan(arguments.get("path") or ".", policy)
    text = _render(result.verdict, header=f"{result.files} file(s) audited")
    return text, result.verdict.to_dict(), False


def _policy(arguments: dict, policy: Policy):
    del arguments
    contract = policy.test_contract
    summary = {
        "project": policy.project_name,
        "source": policy.source,
        "protected_test_patterns": list(contract.protected_patterns),
        "rules": {
            "assertion_monotonicity": _name(contract.assertion_monotonicity),
            "vacuous_assertion": _name(contract.forbid_vacuous_assertions),
            "skip_marker": _name(contract.forbid_new_skip_markers),
            "disabled_assertion": _name(contract.forbid_swallowed_exceptions),
            "dangling_reference": _name(policy.refactor.dangling_reference),
            "export_removed": _name(policy.refactor.export_removed),
            "boundary_violation": _name(policy.boundaries.on_violation),
            "structure": _name(policy.structure.severity),
            "ci_check_removed": _name(policy.ci.check_removed),
            "ci_check_disabled": _name(policy.ci.check_disabled),
        },
        "limits": {
            "max_file_lines": policy.structure.max_file_lines,
            "max_function_lines": policy.structure.max_lines,
            "max_parameters": policy.structure.max_parameters,
            "max_complexity": policy.structure.max_complexity,
            "max_added_lines": policy.structure.max_added_lines,
        },
        "zones": [
            {"name": zone.name, "path": zone.path,
             "forbidden_imports": list(zone.forbidden_imports)}
            for zone in policy.boundaries.zones
        ],
    }
    return json.dumps(summary, indent=2), summary, False


def _render(verdict: Verdict, header: str = "") -> str:
    lines = [header] if header else []
    lines.append(f"verdict: {verdict.status.value}")
    if verdict.skipped:
        lines.append("not evaluated:")
        lines.extend(f"  - {note}" for note in verdict.skipped)
    if not verdict.findings:
        lines.append("No findings.")
        return "\n".join(lines)
    lines.append("")
    lines.append(verdict.prescription)
    return "\n".join(lines)


def _name(status) -> str:
    return status.value if status is not None else "off"


_HANDLERS: dict[str, Callable[[dict, Policy], tuple[str, dict, bool]]] = {
    "aegis_verify_change": _verify_change,
    "aegis_verify_diff": _verify_diff,
    "aegis_review": _review,
    "aegis_scan": _scan,
    "aegis_policy": _policy,
}
