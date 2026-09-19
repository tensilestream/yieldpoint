"""The whole pattern, with no framework at all.

``python examples/plain_loop.py``

If you are integrating Yieldpoint somewhere this repository has no example for,
this is the shape. Everything else — LangGraph nodes, CrewAI steps, MCP tools,
the hook — is this loop with someone else's control flow around it.
"""

from __future__ import annotations

from yieldpoint.core.verdict import Status
from yieldpoint.verify import verify_change

POLICY = {"protected_tests": ["**/test_*.py"]}
MAX_REPAIRS = 3


def run(generate, apply_patch, ask_human, path: str, before: str) -> str:
    """generate -> verify -> (apply | repair | escalate).

    The verification sits between generation and application, which is the only
    placement that matters: the agent proposes, and something it does not
    control decides whether the proposal lands.
    """
    feedback = ""
    for attempt in range(1, MAX_REPAIRS + 1):
        after = generate(before, feedback)
        verdict = verify_change(before, after, path, POLICY)

        if verdict.status is Status.PASS:
            return apply_patch(after)

        if verdict.status is Status.UNVERIFIED:
            # No rule could analyse this. Not a pass — decide deliberately.
            return ask_human(after, "nothing could be verified: " + "; ".join(verdict.skipped))

        if verdict.status is Status.REPAIR and attempt < MAX_REPAIRS:
            # The prescription is assembled from the verdict, not generated.
            # Feeding it back costs no model call to produce.
            feedback = verdict.prescription
            continue

        return ask_human(after, verdict.prescription)

    return ask_human(after, "repair budget exhausted")


# ---------------------------------------------------------------------- demo

BEFORE = "from billing import invoice\n\ndef test_total():\n    assert invoice.total == 42\n"


def main() -> None:
    attempts = iter([
        # First try: make the test pass by weakening it.
        "from billing import invoice\n\ndef test_total():\n    assert invoice.total\n",
        # After reading the prescription: fix the value instead.
        "from billing import invoice\n\ndef test_total():\n    assert invoice.total == 99\n",
    ])

    def generate(before, feedback):
        if feedback:
            print(f"  fed back (0 model calls to produce):\n    "
                  + feedback.strip().replace("\n", "\n    ") + "\n")
        return next(attempts)

    result = run(
        generate=generate,
        apply_patch=lambda after: f"applied:\n    {after.strip().splitlines()[-1].strip()}",
        ask_human=lambda after, why: f"escalated: {why}",
        path="tests/test_invoice.py",
        before=BEFORE,
    )
    print(f"  {result}")


if __name__ == "__main__":
    main()
