"""A verification step between a CrewAI task and whatever commits its output.

CrewAI composes agents into tasks. The placement question is the same as
everywhere else: a guard the agent may skip is not a guard, so this sits in the
callback that receives the task output rather than in the agent's own prompt.
"""

from __future__ import annotations

from aegisflow.core.verdict import Status
from aegisflow.verify import verify_diff

POLICY = ".aegisflow.json"


def guard(task_output, root: str = "."):
    """Use as a CrewAI task ``callback``.

    Returns the output unchanged when the change holds, and raises with the
    prescription when it does not — so the failure carries the fix rather than
    just a rejection.
    """
    diff = getattr(task_output, "raw", str(task_output))
    verdict = verify_diff(diff, root, POLICY)

    if verdict.status is Status.PASS:
        return task_output
    if verdict.status is Status.UNVERIFIED:
        raise ValueError(
            "AegisFlow could not analyse this change, so it is not approved:\n"
            + "\n".join(verdict.skipped)
        )
    raise ValueError(f"AegisFlow rejected this change:\n\n{verdict.prescription}")


def build_task(agent, description: str, root: str = "."):
    """The wiring, for reference."""
    from crewai import Task

    return Task(
        description=description,
        agent=agent,
        callback=lambda output: guard(output, root),
    )


def crew_wide_review(root: str = ".") -> str:
    """Run once after the crew finishes: what did all of them do together?

    Per-agent verification misses a test moved from one agent's file to
    another's — each sees half the change. See langgraph_fanout.py.
    """
    from aegisflow.worktree import uncommitted

    diff = uncommitted(root)
    if not diff.ok:
        return diff.reason
    return verify_diff(diff.text, diff.root, POLICY).prescription or "clean"
