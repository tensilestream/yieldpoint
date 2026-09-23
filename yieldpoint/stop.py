"""The gate that does not depend on how the edit was made.

``hook.py`` verifies a tool call. That only works for tools whose payload
carries enough to reconstruct the file — ``Write`` supplies the content,
``Edit`` supplies the replacement. An agent that edits through a shell instead
(``sed -i``, a heredoc, ``python - <<EOF``, ``patch``) is invisible to it: the
payload is a command string, the command has not run yet, and there is no
after-state to verify. Widening the matcher does not help; there is nothing in
a ``Bash`` payload to check.

That is not an exotic case. Editing through the shell is ordinary agent
behaviour, and some providers have no file-edit tool at all. A gate that only
sees one provider's edit tools enforces nothing in general, and — worse —
*looks* installed while enforcing nothing, which is the failure mode that ends
with a verifier nobody trusts.

So this gate asks a different question. Not "what is this tool about to do" but
"what does the working tree look like now, against the last committed state".
Git answers that no matter who made the change or how, which makes this the
only door that closes for every provider.

It runs when the agent stops. Two constraints follow from that:

**It must never loop.** Blocking a stop sends the agent back to work, and the
next stop runs this hook again. Claude Code sets ``stop_hook_active`` on that
second pass; when it is set, this gate reports and allows, always. An agent
that cannot finish is worse than an unverified one.

**It must fail open.** Not a git repository, git missing, a verifier crash — all
of them allow. Uncertainty resolves toward letting work end, for the same
reason it resolves toward letting an edit through in ``hook.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .core.policy import Policy
from .core.verdict import Status, Verdict

#: Statuses that let the agent stop. ``UNVERIFIED`` is here for the reason it is
#: in ``hook.py``: no rule could analyse the change, so there is nothing to
#: block on, and refusing to let a session end over an unsupported language
#: would make the gate unusable on any polyglot repository.
_ALLOWED = frozenset({Status.PASS, Status.UNVERIFIED})


class Outcome:
    """What the gate found, and why it may have found nothing."""

    policy: Policy | None = None
    """What counts as blocking here. Set by :func:`evaluate` rather than passed,
    so the constructor keeps the shape every existing caller already uses; a
    caller that leaves it unset gets the stricter, pre-existing behaviour."""

    def __init__(self, verdict: Verdict | None = None, *, reason: str = "",
                 root: str = "", analysed: int = 0) -> None:
        self.verdict = verdict
        self.reason = reason
        self.root = root
        self.analysed = analysed

    @property
    def ran(self) -> bool:
        return self.verdict is not None

    @property
    def holds(self) -> bool:
        """Whether the agent should be sent back to fix something.

        Shape findings are reported and never blocking here, for the reason
        ``hook.blocks`` gives and ``structure.gates`` controls. This gate used
        to ignore that, so a change could be waved through on every edit and
        then refused at the door — and ``change_too_large``, whose only remedy
        is a commit the agent is usually not allowed to make, could hold a
        session open with nothing it could legally do to satisfy it.
        """
        if self.verdict is None:
            return False
        if self.verdict.status in _ALLOWED or not self.verdict.findings:
            return False
        if self.policy is not None:
            from .commands import only_maintainability

            if only_maintainability(self.verdict, self.policy):
                return False
        return True


def suppressed(payload: dict[str, Any]) -> bool:
    """Whether this is the second pass, and blocking again would loop.

    Claude Code sets ``stop_hook_active`` when the agent was resumed *by* a stop
    hook. Both spellings are accepted because the payload key has been written
    in each, and guessing wrong here means an agent that can never stop.
    """
    return bool(payload.get("stop_hook_active") or payload.get("stopHookActive"))


def evaluate(root: str | Path = ".", policy: Policy | str | None = None) -> Outcome:
    """Verify everything uncommitted. Never raises."""
    from .core.locate import repository
    from .core.parsecache import configure
    from .verify import verify_diff
    from .worktree import uncommitted

    try:
        base = Path(root)
        configure(repository(base))
        resolved = Policy.load(policy)
        diff = uncommitted(base)
        if not diff.ok:
            return Outcome(reason=diff.reason, root=str(base))
        verdict = verify_diff(diff.text, root=diff.root, policy=resolved)
        outcome = Outcome(verdict, root=diff.root, analysed=len(diff.text))
        outcome.policy = resolved
        return outcome
    except Exception as exc:  # a verifier crash must never trap the agent
        return Outcome(reason=f"verifier error — {exc}", root=str(root))


def _headline(verdict: Verdict) -> str:
    """What was actually found — the same distinction ``hook.py`` draws.

    Saying "weakens what the test suite verifies" over a function-length finding
    is a lie the reader can check, and it costs more credibility than the
    stronger wording buys.
    """
    from .hook import _CONTRACT_RULES

    rules = {f.rule for f in verdict.findings}
    contract = rules & _CONTRACT_RULES
    opening = "Yieldpoint checked the whole working tree before you stopped."
    if contract and rules - contract:
        return (f"{opening} It weakens what the test suite verifies, and breaks "
                "a project rule.")
    if contract:
        return f"{opening} It weakens what the test suite verifies."
    return f"{opening} It breaks a rule this project enforces."


def render(outcome: Outcome) -> str:
    """The message the agent reads when it is sent back."""
    verdict = outcome.verdict
    if verdict is None:
        return ""
    lines = [
        _headline(verdict),
        "",
        "Checked here as well as on each edit because an edit made through the "
        "shell never reaches a per-tool gate.",
        "",
    ]
    for finding in verdict.findings:
        where = f"{finding.file}:{finding.line}"
        symbol = f" in {finding.symbol}" if finding.symbol else ""
        lines.append(f"  {where}{symbol}  [{finding.rule}]")
        lines.append(f"    {finding.detail}")
        lines.append(f"    Fix: {finding.prescription}")
        lines.append("")
    lines.append(_ways_out(verdict.findings, outcome.root))
    return "\n".join(lines)


def _placeable(finding) -> bool:
    """Whether an acknowledgement has a line to sit on.

    Not every finding does. ``change_too_large`` is reported against the change
    itself — "24 files", line 0 — so there is no source to write a comment in.
    Offering that route anyway advertises an escape hatch the reader cannot
    take, and sends them looking for a file that does not exist.
    """
    return finding.line > 0


def _ways_out(findings, root) -> str:
    """What the reader can actually do, given what was found."""
    from .policyfile import where

    out = f"Fix these, then stop. If a rule is wrong for this repository, {where(root)}"
    if any(_placeable(f) for f in findings):
        out += (", or acknowledge the finding in the source with "
                "`# yieldpoint: allow <rule> - reason`")
    else:
        out += (". A finding about the change as a whole has no line to "
                "acknowledge: land it in smaller pieces instead")
    return out + ", rather than working around it."


def summary(outcome: Outcome) -> str:
    """One line for the person watching, who did not ask for the full report."""
    verdict = outcome.verdict
    if verdict is None or not verdict.findings:
        return ""
    count = len(verdict.findings)
    files = len({f.file for f in verdict.findings})
    noun = "finding" if count == 1 else "findings"
    return (f"Yieldpoint: {count} {noun} in {files} file(s) of uncommitted work — "
            "run `yieldpoint review` for the detail.")


def decision(outcome: Outcome, *, advisory: bool, looped: bool = False) -> dict[str, Any]:
    """The Stop-hook response.

    Advisory mode tells the person and lets the agent stop. Enforcing mode sends
    the agent back with the prescriptions attached — the only way a hook has of
    routing work back around the loop.
    """
    if not outcome.holds:
        return {}
    note = summary(outcome)
    if advisory or looped:
        payload: dict[str, Any] = {"systemMessage": note}
        if looped:
            payload["systemMessage"] = (
                f"{note} Not blocking: already resumed once by this hook."
            )
        return payload
    return {"decision": "block", "reason": render(outcome), "systemMessage": note}


def decision_json(outcome: Outcome, *, advisory: bool, looped: bool = False) -> str:
    return json.dumps(decision(outcome, advisory=advisory, looped=looped))
