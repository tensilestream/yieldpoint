"""The verification node.

A LangGraph node is a callable taking state and returning a state update, so
this module imports nothing from LangGraph and works with any graph library
using that convention. It is also testable without installing anything.

Placing this node on the edge between generation and application is what makes
enforcement *topological*: the agent cannot route around a node it does not
control, because the graph does the routing.

State contract, all keys overridable:

    in   ``diff`` (unified diff) and ``root``
         or ``changes``: [{"path":…, "before":…, "after":…}]
    out  ``verdict``      the serialised Verdict
         ``prescription`` deterministic remediation text, ready to feed back
         ``aegis_history`` loop-detection signatures
         ``aegis_attempts`` how many times this node has run
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from ..core.policy import Policy
from ..core.verdict import Status, Verdict
from ..verify import verify_change, verify_diff
from .breaker import DEFAULT_MAX_REPEATS, DEFAULT_WINDOW, HISTORY_KEY, observe, signature

ATTEMPTS_KEY = "aegis_attempts"
TRIPPED_KEY = "aegis_loop_tripped"
VERDICT_KEY = "verdict"
PRESCRIPTION_KEY = "prescription"

Extractor = Callable[[Mapping[str, Any]], "dict | None"]


def verify_node(
    policy: Policy | str | dict | None = None,
    *,
    root: str = ".",
    extract: Extractor | None = None,
    verdict_key: str = VERDICT_KEY,
    window: int = DEFAULT_WINDOW,
    max_repeats: int = DEFAULT_MAX_REPEATS,
) -> Callable[[Mapping[str, Any]], dict]:
    """Build the node. ``extract`` overrides the default state convention."""
    resolved = Policy.load(policy)
    reader = extract or read_change

    def node(state: Mapping[str, Any]) -> dict:
        from ..ledger import Run, Timer, record_run

        request = reader(state)
        with Timer() as timer:
            verdict = _run(request, resolved, root)

        # Recorded here rather than in verify_change: a node is a surface, and
        # the core stays free of clocks and filesystem writes (RULES.md 4).
        # Without this a graph — the surface the product is built for — is the
        # one that shows nothing in `aegisflow stats`.
        record_run(
            verdict,
            Run("langgraph", len(_payload(request)), timer.elapsed_ms, root),
            resolved,
        )

        history, tripped = observe(
            state.get(HISTORY_KEY),
            signature(_payload(request), verdict.to_json()),
            window=window,
            max_repeats=max_repeats,
        )
        return {
            verdict_key: verdict.to_dict(),
            PRESCRIPTION_KEY: verdict.prescription,
            HISTORY_KEY: history,
            ATTEMPTS_KEY: int(state.get(ATTEMPTS_KEY, 0)) + 1,
            TRIPPED_KEY: tripped,
        }

    return node


def read_change(state: Mapping[str, Any]) -> dict | None:
    """Default state convention. Returns ``None`` when no change is present."""
    for key in ("diff", "aegis_diff"):
        if state.get(key):
            return {"diff": state[key], "root": state.get("root")}
    for key in ("changes", "aegis_changes"):
        entries = state.get(key)
        if entries:
            return {"changes": [dict(entry) for entry in entries]}
    return None


def verdict_from(state: Mapping[str, Any], key: str = VERDICT_KEY) -> Verdict:
    """Rehydrate the Verdict a node stored. State holds plain dicts so that
    checkpointers can serialise it."""
    raw = state.get(key)
    if isinstance(raw, Verdict):
        return raw
    if isinstance(raw, dict):
        return Verdict.from_dict(raw)
    return Verdict.of([])


def _run(request: dict | None, policy: Policy, root: str) -> Verdict:
    if request is None:
        # No change in state is not a clean change; say so rather than pass.
        return Verdict.of([], skipped=["no change found in state"])

    if "diff" in request:
        return verify_diff(request["diff"], request.get("root") or root, policy)

    verdict = Verdict.of([])
    for entry in request.get("changes", []):
        path = entry.get("path")
        if not path:
            verdict = verdict.merge(Verdict.of([], skipped=["change without a path"]))
            continue
        verdict = verdict.merge(
            verify_change(entry.get("before"), entry.get("after"), path, policy)
        )
    return verdict


def _payload(request: dict | None) -> str:
    """The proposed content, for loop detection. Distinct edits differ here."""
    if not request:
        return ""
    if "diff" in request:
        return str(request["diff"])
    return "\x00".join(
        f"{e.get('path', '')}\x01{e.get('after', '')}" for e in request.get("changes", [])
    )


__all__ = ["verify_node", "read_change", "verdict_from", "Status"]
