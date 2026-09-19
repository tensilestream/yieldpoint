"""The two places this plugs into an agent loop.

An agent loop is: a model decides, a tool runs, something judges the result,
repeat. There are exactly two useful places to insert a computed decision, and
they save different things.

**Before the model** — pick how much model this work needs. A docstring fix and
a module restructure cost the same otherwise. Asking a model which one it is
adds a round trip to save one, and is not reproducible; reading it off the
syntax tree is free and is.

**Before the tool** — check the edit before it is written, not after the tests
fail. The saving here is larger and less obvious: a bad edit that lands costs
the test run, the failure output, the model's reasoning about the failure, and
the retry. Refusing it up front replaces all of that with a sentence saying what
to restore.

Neither wraps the model or the tool. They take what the loop already has and
return a decision, so this works the same in LangGraph, an SDK with hooks, a
CrewAI callback, or a while loop somebody wrote.

``Middleware`` keeps no state between calls and reads no clock, so the same
request decides the same way on any machine and concurrent agents cannot
interfere with each other.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.policy import Policy
from ..core.verdict import Status
from ..verify import verify_change
from .decisions import Choice, Gate
from .routing import model_for, tier
from .signals import Change, measure

#: A reasonable default mapping. Override it with your own model names.
DEFAULT_TIERS = {
    "small": "small",
    "standard": "standard",
    "capable": "capable",
}

EDIT_TOOLS = ("Edit", "MultiEdit", "Write", "str_replace_editor", "apply_patch")


@dataclass(frozen=True)
class Middleware:
    """Computed decisions for an agent loop. Stateless and reproducible."""

    policy: Policy | str | dict | None = None
    tiers: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_TIERS))
    escalate_to: str | None = None
    """Where ``human`` routes. ``None`` means the caller handles it."""

    def before_model(self, change: Change, *, verified: bool | None = None) -> Choice:
        """Which model this work needs. Costs one parse, no round trip."""
        return tier(change, self.policy, verified=verified)

    def model_name(self, change: Change, *, verified: bool | None = None) -> str | None:
        """Convenience: straight to a model name, or ``None`` to make no call."""
        decision = self.before_model(change, verified=verified)
        if decision.value == "human":
            return self.escalate_to
        return model_for(decision, self.tiers)

    def before_tool(self, name: str, arguments: dict) -> Gate:
        """Allow or deny a tool call, before it runs.

        Only edit tools are judged. Anything else is allowed with a reason
        saying why it was not examined — silence would read as approval, which
        is the thing this project exists not to do.
        """
        if name not in EDIT_TOOLS:
            return Gate(
                question="before_tool", value=True,
                reason=f"{name} does not modify files; not examined",
            )

        change = self._change_from(arguments)
        if change is None:
            return Gate(
                question="before_tool", value=True,
                reason="could not reconstruct the edit from this payload; allowing",
            )

        verdict = verify_change(change.before, change.after, change.path, self.policy)
        if verdict.status in (Status.PASS, Status.UNVERIFIED):
            return Gate(
                question="before_tool", value=True,
                reason=verdict.status.value,
                signals={"status": verdict.status.value, "path": change.path},
            )
        return Gate(
            question="before_tool", value=False,
            reason=verdict.findings[0].detail if verdict.findings else verdict.status.value,
            prescription=verdict.prescription,
            signals={
                "status": verdict.status.value,
                "path": change.path,
                "rules": sorted({f.rule for f in verdict.findings}),
            },
        )

    def assess(self, change: Change) -> dict:
        """Every decision about one change, in one parse.

        A harness usually wants several of these at once, and computing the
        signals once for all of them is the difference between this being free
        and merely cheap.
        """
        from .routing import risk

        found = measure(change, self.policy)
        return {
            "signals": found.to_dict(),
            "risk": risk(change, self.policy, signals=found).to_dict(),
            "tier": tier(change, self.policy, signals=found).to_dict(),
        }

    # ------------------------------------------------------------- internals

    def _change_from(self, arguments: dict) -> Change | None:
        """Reconstruct before/after from a tool payload.

        Reuses the hook's reconstruction so the gate and the hook cannot
        disagree about what an edit does (RULES.md section 3).
        """
        from ..hook import build_change

        for tool in EDIT_TOOLS:
            built = build_change({"tool_name": tool, "tool_input": arguments})
            if built.usable:
                return Change(path=built.path, before=built.before, after=built.after)
        return None


def middleware(policy=None, tiers: dict[str, str] | None = None,
               escalate_to: str | None = None) -> Middleware:
    """Build the middleware. Kept as a function so the class can change shape."""
    return Middleware(
        policy=policy,
        tiers=dict(tiers or DEFAULT_TIERS),
        escalate_to=escalate_to,
    )


__all__ = ["Middleware", "middleware", "DEFAULT_TIERS", "EDIT_TOOLS"]
