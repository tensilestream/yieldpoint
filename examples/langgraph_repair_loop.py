"""A LangGraph agent that tries to cheat, gets caught, and converges.

Run it:

    pip install langgraph
    python examples/langgraph_repair_loop.py

The "model" here is scripted rather than real, so the example is deterministic
and runs in CI. It reproduces the behaviour that motivates this project: asked to
make a failing test pass, the agent's first move is to weaken the assertion.

What to notice is where the verification sits. ``verify`` is on the edge between
``generate`` and ``apply``, so the agent cannot reach ``apply`` without passing
through it. Enforcement is a property of the graph's shape, not of the model's
willingness to cooperate.
"""

from __future__ import annotations

import operator
import sys
from pathlib import Path
from typing import Annotated, TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langgraph.graph import END, START, StateGraph  # noqa: E402

from yieldpoint.langgraph import (  # noqa: E402
    BLOCK, ESCALATE, PASS, REPAIR, make_router, repair_context, verify_node,
)

TEST_PATH = "tests/test_invoice.py"

ORIGINAL_TEST = '''def test_total():
    inv = build(qty=2, price=21)
    assert inv.total == Decimal("42.00")
'''

# The agent's first instinct: make the test agree with the broken code.
WEAKENED_TEST = '''def test_total():
    inv = build(qty=2, price=21)
    assert inv.total is not None
'''

model_calls = 0


class State(TypedDict, total=False):
    changes: list
    verdict: dict
    prescription: str
    yieldpoint_history: list
    yieldpoint_attempts: int
    yieldpoint_loop_tripped: bool
    outcome: str
    log: Annotated[list[str], operator.add]


def generate(state: State) -> dict:
    """The scripted 'model'. Every call here is a real model call in production."""
    global model_calls
    model_calls += 1
    feedback = state.get("prescription") or ""

    if not feedback:
        after = WEAKENED_TEST
        note = f"call {model_calls}: weakened the assertion to make the suite green"
    else:
        # The prescription named the subject and the strength to restore, so the
        # agent knows what to do without another round of trial and error.
        after = ORIGINAL_TEST
        note = f"call {model_calls}: restored the assertion and fixed the source instead"

    return {
        "changes": [{"path": TEST_PATH, "before": ORIGINAL_TEST, "after": after}],
        "log": [note],
    }


def apply_patch(state: State) -> dict:
    return {"outcome": "applied", "log": ["applied the change"]}


def human_review(state: State) -> dict:
    return {"outcome": "escalated", "log": ["escalated to a human"]}


def build_graph():
    graph = StateGraph(State)
    graph.add_node("generate", generate)
    graph.add_node("verify", verify_node())          # <- the whole integration
    graph.add_node("apply", apply_patch)
    graph.add_node("review", human_review)

    graph.add_edge(START, "generate")
    graph.add_edge("generate", "verify")
    graph.add_conditional_edges(
        "verify",
        make_router(max_repairs=3),
        {
            PASS: "apply",        # verified: let it through
            REPAIR: "generate",   # fixable: hand back the prescription, no model call spent
            ESCALATE: "review",   # budget spent or loop stalled: ask a human
            BLOCK: "review",
        },
    )
    graph.add_edge("apply", END)
    graph.add_edge("review", END)
    return graph.compile()


def main() -> int:
    final = build_graph().invoke({"log": []})

    print("Agent transcript")
    print("-" * 64)
    for entry in final["log"]:
        print(f"  {entry}")

    print(f"\nOutcome         : {final['outcome']}")
    print(f"Verify attempts : {final.get('yieldpoint_attempts')}")
    print(f"Model calls     : {model_calls}")
    print(
        "Prescription    : produced deterministically, 0 model calls\n"
        "                  (an LLM-as-judge would add one call per repair round)"
    )

    assert final["outcome"] == "applied", "the loop should converge, not escalate"
    assert model_calls == 2, f"expected 2 model calls, got {model_calls}"
    print("\nThe cheat was caught before it was applied, and the agent converged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
