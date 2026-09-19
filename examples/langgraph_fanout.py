"""Many workers, one repository — the shape a large migration actually takes.

Run with ``python examples/langgraph_fanout.py``. No LangGraph install required:
the fan-out is simulated so the *verification* behaviour is what you see, and
the graph wiring is shown in ``build_graph`` for when you have LangGraph.

Two mistakes are easy here and both are corrected below.

**Verifying each worker in isolation.** Worker A moves a test into a module
worker B owns. A's diff loses a subject; B's diff gains one. Verified
separately, A is reported as weakening the suite and B as doing nothing. Pool
the subjects first — the verdict is about the change set, not about one worker.

**Not labelling the workers.** With three hundred of them, "the suite got
weaker" is a fact nobody can act on. ``YIELDPOINT_RUN_ID`` and
``YIELDPOINT_AGENT`` make ``yieldpoint stats`` report findings per agent, which
turns it into "worker 47 keeps doing this".
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from yieldpoint.core.relation import Relation
from yieldpoint.core.verdict import Status, Verdict
from yieldpoint.verify import verify_change


@dataclass(frozen=True)
class Edit:
    """What one worker produced."""

    agent: str
    path: str
    before: str
    after: str


def pooled_subjects(edits: list[Edit], policy) -> dict[str, Relation]:
    """Subjects asserted anywhere in the change set, at their strongest.

    This is the fix for a test moving between workers. Passing it as
    ``also_covered`` tells each verification that a subject missing *here* may
    still be verified *there*.
    """
    from yieldpoint.core.assertions import extract
    from yieldpoint.core.monotonicity import subject_map

    pooled: dict[str, Relation] = {}
    for edit in edits:
        if not edit.path.endswith(".py"):
            continue
        extraction = extract(edit.after, filename=edit.path)
        if not extraction.ok:
            continue
        for subject, relation in subject_map(extraction).items():
            current = pooled.get(subject)
            if current is None or relation.rank > current.rank:
                pooled[subject] = relation
    return pooled


def verify_fanout(edits: list[Edit], policy=None) -> dict[str, Verdict]:
    """Verify every worker's edit against the *whole* change set."""
    covered = pooled_subjects(edits, policy)
    return {
        edit.agent: verify_change(
            edit.before, edit.after, edit.path, policy, also_covered=covered
        )
        for edit in edits
    }


def label_worker(run: str, agent: str) -> None:
    """Call this in each worker before it verifies anything."""
    os.environ["YIELDPOINT_RUN_ID"] = run
    os.environ["YIELDPOINT_AGENT"] = agent


# --------------------------------------------------------------------- graph

def build_graph(policy=None):
    """The LangGraph wiring. Kept out of the demo so this file runs anywhere.

    ``Send`` fans out to one worker per unit of work; the barrier after it is
    what makes pooled verification possible. Verifying inside each worker — the
    obvious design — is the isolation mistake described at the top.
    """
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import Send

    from yieldpoint.langgraph import make_router

    def plan(state):
        return {"units": state["units"]}

    def dispatch(state):
        return [Send("worker", {"unit": unit}) for unit in state["units"]]

    def worker(state):
        return {"edits": [do_work(state["unit"])]}

    def verify_all(state):
        verdicts = verify_fanout(state["edits"], policy)
        worst = Status.worst(v.status for v in verdicts.values())
        merged = Verdict.of(
            [f for v in verdicts.values() for f in v.findings],
            checked=[c for v in verdicts.values() for c in v.checked],
        )
        return {"verdict": merged.to_dict(), "status": worst.value}

    builder = StateGraph(dict)
    builder.add_node("plan", plan)
    builder.add_node("worker", worker)
    builder.add_node("verify", verify_all)
    builder.add_edge(START, "plan")
    builder.add_conditional_edges("plan", dispatch, ["worker"])
    builder.add_edge("worker", "verify")          # barrier: all workers land first
    builder.add_conditional_edges("verify", make_router(), {
        "pass": END, "repair": "plan", "escalate": END, "block": END,
        "unverified": END,
    })
    return builder.compile()


def do_work(unit):  # pragma: no cover - placeholder for a real worker
    raise NotImplementedError("your agent goes here")


# ---------------------------------------------------------------------- demo

ORIGINAL = '''\
from billing import invoice

def test_invoice_total():
    assert invoice.total == 42

def test_invoice_currency():
    assert invoice.currency == "GBP"
'''

# Worker A moves test_invoice_currency out of this file.
A_AFTER = '''\
from billing import invoice

def test_invoice_total():
    assert invoice.total == 42
'''

# Worker B receives it, unchanged.
B_BEFORE = "from billing import shipping\n\ndef test_shipping():\n    assert shipping.cost == 5\n"
B_AFTER = '''\
from billing import invoice, shipping

def test_shipping():
    assert shipping.cost == 5

def test_invoice_currency():
    assert invoice.currency == "GBP"
'''


def main() -> None:
    policy = {"protected_tests": ["**/test_*.py"]}
    edits = [
        Edit("worker-a", "tests/test_invoice.py", ORIGINAL, A_AFTER),
        Edit("worker-b", "tests/test_shipping.py", B_BEFORE, B_AFTER),
    ]

    print("Verified in isolation — each worker sees half the change:")
    for edit in edits:
        verdict = verify_change(edit.before, edit.after, edit.path, policy)
        print(f"  {edit.agent:10} {verdict.status.value:11} "
              f"{[f.detail for f in verdict.findings] or 'clean'}")

    print("\nVerified against the pooled change set:")
    for agent, verdict in verify_fanout(edits, policy).items():
        print(f"  {agent:10} {verdict.status.value:11} "
              f"{[f.detail for f in verdict.findings] or 'clean'}")

    print("\nThe move is not a weakening, and only the pooled view knows that.")


if __name__ == "__main__":
    main()
