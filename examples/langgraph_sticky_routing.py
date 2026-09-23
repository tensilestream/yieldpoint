"""Admit a model once; allow one replacement only after verification fails.

Run after installing the optional LangGraph extra:

    pip install "yieldpoint[langgraph]"
    python examples/langgraph_sticky_routing.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from yieldpoint.langgraph import (  # noqa: E402
    HANDOFF_EVENT_KEY, PROFILE_KEY, SESSION_KEY, make_admission_node,
    make_handoff_router,
)


def main() -> int:
    """Exercise JSON-safe graph state without selecting a real provider model."""
    state = {
        "task": "Repair a cross-SDK package release",
        "changes": [{"path": "sdk/node/src/router.js", "before": "export {}", "after": "export const ok = true\n"}],
    }
    state.update(make_admission_node(task_id="release-42", selected_model="standard")(state))
    router = make_handoff_router(candidate_capabilities=frozenset({
        "multilingual_sdk", "tool_use", "strong_reasoning",
    }))

    assert router(state) == "escalate", "normal work must keep its admitted model"
    state[HANDOFF_EVENT_KEY] = "verification_failed"
    assert router(state) == "handoff", "a failed verification is an explicit checkpoint"

    print(f"Profile: {state[PROFILE_KEY]['profile_id']}")
    print(f"Admitted model: {state[SESSION_KEY]['selected_model']}")
    print("Handoff: allowed only after verification_failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
