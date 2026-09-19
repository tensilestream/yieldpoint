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
from .core.verdict import Finding, Status, Verdict
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
    from .core.locate import repository
    from .core.parsecache import configure

    configure(repository(Path.cwd()))
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
    if not blocks(verdict):
        allowed: dict = {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
        }
        postponed = deferred(verdict)
        if postponed:
            # Allowed, but say so out loud. Silence here would be the green
            # banner: the edit went through and something was left unchecked.
            allowed["permissionDecisionReason"] = (
                f"{len(postponed)} finding(s) deferred to the full change set; "
                "run `yieldpoint review` before committing."
            )
        payload = {"hookSpecificOutput": allowed}
    else:
        payload = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": render(verdict, change),
            }
        }
    return json.dumps(payload)


#: Rules that mean the test suite lost verification strength. Anything else is
#: about the shape of the code, and saying otherwise in the block message is a
#: small lie the reader can check — which costs more credibility than it saves.
_CONTRACT_RULES = frozenset({
    "assertion_monotonicity", "vacuous_assertion",
    "empty_test", "skip_marker", "disabled_assertion",
})


def _headline(verdict: Verdict) -> str:
    rules = {f.rule for f in immediate(verdict)}
    contract = rules & _CONTRACT_RULES
    if contract and rules - contract:
        return ("Yieldpoint blocked this edit: it weakens what the test suite "
                "verifies, and breaks a project rule.")
    if contract:
        return "Yieldpoint blocked this edit: it weakens what the test suite verifies."
    return "Yieldpoint blocked this edit: it breaks a rule this project enforces."


def render_deferred(verdict: Verdict) -> str:
    """The note shown when an edit is allowed with something left to check.

    Distinct from ``render`` because that one opens with "blocked", and
    printing it on an edit that was permitted is worse than printing nothing:
    the reader learns that the wording cannot be trusted.
    """
    postponed = deferred(verdict)
    if not postponed:
        return ""
    lines = [
        "Yieldpoint allowed this edit, with "
        f"{len(postponed)} finding(s) left to check.",
        "",
        "One edit cannot tell moving a test from deleting one, so these are "
        "judged against the whole change set instead:",
        "",
    ]
    for finding in postponed:
        lines.append(f"  {finding.location}  {finding.detail}")
    lines += ["", "Run `yieldpoint review` before you commit."]
    return "\n".join(lines)


def render(verdict: Verdict, change: Change) -> str:
    """The message the agent reads. Must say what broke and what to do."""
    lines = [_headline(verdict), ""]
    del change  # reserved for future per-tool context in the message
    for finding in immediate(verdict):
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
    elif {f.rule for f in verdict.findings} & _CONTRACT_RULES:
        lines.append(
            "Fix the code under test so the original assertions pass, rather than "
            "changing the assertions. If the test is genuinely wrong, say so "
            "explicitly and explain why before editing it."
        )
    else:
        lines.append(
            "Apply the fix above. If the rule is wrong for this repository, change "
            "it in .yieldpoint.json rather than working around it."
        )
    postponed = deferred(verdict)
    if postponed:
        lines.append("")
        lines.append(
            "Not judged here, because one edit is not enough to tell a move from "
            "a deletion — these are checked again before the change lands:"
        )
        for finding in postponed:
            lines.append(f"  {finding.location}  {finding.detail}")

    running = _running_total()
    if running:
        lines += ["", running]
    return "\n".join(lines)


def _running_total() -> str:
    """The ledger line the agent sees on every blocked edit. Never raises."""
    try:
        from . import ledger
        from .report import running_line
        from .totals import totals

        policy = Policy()
        if not ledger.enabled(policy):
            return ""
        return running_line(totals(ledger.path_for(policy)))
    except Exception:  # a report must never be why an edit fails
        return ""


#: Finding kinds a single-edit gate cannot fairly judge.
#:
#: A ``PreToolUse`` hook sees one edit and cannot see the next one. Moving a
#: test to another file begins by deleting it from this one, which is
#: indistinguishable — at this instant — from deleting it. Blocking that is the
#: false positive that gets a hook switched off during the first real refactor,
#: and a hook that is off catches nothing at all.
#:
#: So a *removal* is deferred to where the whole change set is visible:
#: ``yieldpoint review``, pre-commit, or CI, all of which pool subjects across
#: files and can tell a move from a deletion. Nothing is lost except immediacy.
#:
#: The distinction is narrow on purpose. Only a *whole test disappearing* is
#: deferred, because that is what moving one looks like. Deleting an assertion
#: from a test that is still there is refused on the spot — nobody relocates a
#: single assertion, and quietly dropping one is the most common tampering
#: there is. Downgrading in place is likewise refused: rewriting
#: ``assert x == 1`` as ``assert x`` is no part of any multi-file operation.
DEFERRED_KINDS = frozenset({"test_removed"})

#: Statuses that let an edit through. ``UNVERIFIED`` is here because the hook
#: fails open: no rule could analyse the change, and denying every edit to an
#: unsupported language would make the hook unusable on any polyglot repository.
#: The graph is where that decision is made — ``make_router(on_unverified=...)``
#: — because a graph has somewhere to route to and a hook has only allow or deny.
_ALLOWED = frozenset({Status.PASS, Status.UNVERIFIED})


def deferred(verdict: Verdict) -> tuple[Finding, ...]:
    """Findings this gate will not judge, because it cannot see enough."""
    return tuple(f for f in verdict.findings if f.kind in DEFERRED_KINDS)


def immediate(verdict: Verdict) -> tuple[Finding, ...]:
    """Findings a single edit is enough to be sure about."""
    return tuple(f for f in verdict.findings if f.kind not in DEFERRED_KINDS)


def blocks(verdict: Verdict) -> bool:
    """Whether this verdict should deny the edit.

    In a graph, ``REPAIR`` routes back to generation. A hook has no router — its
    only way to send the agent back around the loop is to deny with the
    prescription attached, so ``REPAIR`` denies here too. Severity still matters
    for the wording: ``ESCALATE`` tells the agent to stop and ask.

    Nothing analysed means nothing to deny on. The verdict still says
    ``unverified`` and the skipped files are still reported, so the fact is not
    hidden — it just does not stand between a person and their editor.
    """
    if verdict.status in _ALLOWED:
        return False
    return bool(immediate(verdict))


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
