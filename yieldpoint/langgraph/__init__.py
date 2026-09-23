"""LangGraph adapter. Imports nothing from LangGraph: a node is a callable."""

from .breaker import HISTORY_KEY, observe, signature
from .node import ATTEMPTS_KEY, TRIPPED_KEY, VERDICT_KEY, read_change, verdict_from, verify_node
from .router import (
    BLOCK, ESCALATE, PASS, REPAIR, UNVERIFIED,
    make_router, repair_context, route_on_verdict,
)
from .session import (
    HANDOFF_EVENT_KEY, OVERHEAD_KEY, PROFILE_KEY, SESSION_KEY,
    make_admission_node, make_handoff_router,
)

__all__ = [
    "verify_node", "route_on_verdict", "make_router", "repair_context",
    "verdict_from", "read_change", "observe", "signature",
    "PASS", "REPAIR", "ESCALATE", "BLOCK", "UNVERIFIED",
    "HISTORY_KEY", "ATTEMPTS_KEY", "TRIPPED_KEY", "VERDICT_KEY",
    "PROFILE_KEY", "SESSION_KEY", "HANDOFF_EVENT_KEY", "OVERHEAD_KEY",
    "make_admission_node", "make_handoff_router",
]
