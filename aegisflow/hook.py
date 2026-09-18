"""Claude Code PreToolUse hook.

Reads a tool-call payload on stdin, reconstructs the before and after content of
the target file, and verifies the transition before the edit is applied.

Reconstruction is exact and needs no diff parser: ``Write`` supplies the whole
new content, and ``Edit``/``MultiEdit`` supply string replacements applied to the
file already on disk.

**Failures allow.** If the payload cannot be parsed, the file cannot be read, or
a replacement does not apply cleanly, the hook permits the edit. Blocking an
agent because the verifier got confused would make the tool worse than useless,
so uncertainty always resolves toward letting work continue.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .core.policy import Policy
from .core.verdict import Status, Verdict
from .verify import verify_change

EDIT_TOOLS = ("Edit", "MultiEdit", "Write", "NotebookEdit")


@dataclass(frozen=True)
class Change:
    """A reconstructed file transition, or a reason none could be built."""

    path: str = ""
    before: str | None = None
    after: str | None = None
    reason: str | None = None

    @property
    def usable(self) -> bool:
        return self.reason is None and bool(self.path)


def read_payload(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def build_change(payload: dict[str, Any]) -> Change:
    """Reconstruct before/after content from a PreToolUse payload."""
    tool = payload.get("tool_name") or payload.get("toolName") or ""
    tool_input = payload.get("tool_input") or payload.get("toolInput") or {}
    if not isinstance(tool_input, dict):
        return Change(reason="tool_input is not an object")
    if tool not in EDIT_TOOLS:
        return Change(reason=f"{tool or 'unknown tool'} does not modify files")

    path = tool_input.get("file_path") or tool_input.get("path") or tool_input.get("notebook_path")
    if not path:
        return Change(reason="payload carries no file path")

    before = _read(Path(path))

    if tool == "Write":
        return Change(path=path, before=before, after=tool_input.get("content", ""))

    if before is None:
        return Change(reason=f"cannot read {path} to reconstruct the edit")

    edits = tool_input.get("edits")
    if not isinstance(edits, list):
        edits = [tool_input]

    after = before
    for edit in edits:
        if not isinstance(edit, dict):
            return Change(reason="malformed edit entry")
        old = edit.get("old_string", edit.get("new_source"))
        new = edit.get("new_string", edit.get("new_source"))
        if old is None or new is None:
            return Change(reason="edit is missing old_string/new_string")
        if old not in after:
            return Change(reason="old_string not found; cannot reconstruct the result")
        after = after.replace(old, new, -1 if edit.get("replace_all") else 1)

    return Change(path=path, before=before, after=after)


def evaluate(payload: dict[str, Any], policy: Policy | str | None = None) -> tuple[Verdict, Change]:
    """Verify the change described by ``payload``. Never raises."""
    change = build_change(payload)
    if not change.usable:
        return Verdict.of([]), change
    try:
        resolved = Policy.load(policy if policy is not None else _policy_for(change.path))
        verdict = verify_change(
            change.before, change.after, _relative(change.path), resolved, hand_edit=True
        )
    except Exception as exc:  # a verifier crash must never block an edit
        return Verdict.of([], skipped=[f"{change.path}: verifier error — {exc}"]), change
    return verdict, change


def decision_json(verdict: Verdict, change: Change) -> str:
    """The structured PreToolUse response."""
    if verdict.status is Status.PASS:
        payload = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
            }
        }
    else:
        payload = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": render(verdict, change),
            }
        }
    return json.dumps(payload)


def render(verdict: Verdict, change: Change) -> str:
    """The message the agent reads. Must say what broke and what to do."""
    lines = [
        "AegisFlow blocked this edit: it weakens what the test suite verifies.",
        "",
    ]
    del change  # reserved for future per-tool context in the message
    for finding in verdict.findings:
        where = f"{finding.file}:{finding.line}"
        symbol = f" in {finding.symbol}" if finding.symbol else ""
        lines.append(f"  {where}{symbol}  [{finding.rule}]")
        lines.append(f"    {finding.detail}")
        lines.append(f"    Fix: {finding.prescription}")
        lines.append("")
    if verdict.status.severity >= Status.ESCALATE.severity:
        lines.append(
            "Stop and ask the user before proceeding. Do not work around this by "
            "editing the test another way."
        )
    else:
        lines.append(
            "Fix the code under test so the original assertions pass, rather than "
            "changing the assertions. If the test is genuinely wrong, say so "
            "explicitly and explain why before editing it."
        )
    return "\n".join(lines)


def blocks(verdict: Verdict) -> bool:
    """Any non-passing verdict denies the edit.

    In a graph, ``REPAIR`` routes back to generation. A hook has no router — its
    only way to send the agent back around the loop is to deny with the
    prescription attached, so ``REPAIR`` denies here too. Severity still matters
    for the wording: ``ESCALATE`` tells the agent to stop and ask.
    """
    return verdict.status is not Status.PASS


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _policy_for(path: str) -> Policy:
    found = Policy.discover(Path(path).parent if Path(path).parent.exists() else Path.cwd())
    return Policy.load(found) if found else Policy()


def _relative(path: str) -> str:
    """Report repository-relative paths so policy globs behave predictably."""
    try:
        return str(Path(path).resolve().relative_to(Path.cwd().resolve()))
    except (ValueError, OSError):
        return path
