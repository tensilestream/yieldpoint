"""What Yieldpoint offers over MCP.

Deliberately small. An MCP tool is **advisory**: the agent decides whether to
call it, so an agent intent on weakening a test will simply not ask. That is not
a flaw to be papered over — it is why `yieldpoint hook` exists, and why the
LangGraph node sits on the graph edge where the agent cannot route around it.

What MCP is genuinely good at is the other half: **explanation**. A blocked agent
otherwise burns tokens guessing why. These tools let it ask directly, and get a
deterministic answer for free.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from ..core.policy import Policy
from ..ledger import Run, record_run
from ..core.verdict import Verdict
from ..verify import verify_change, verify_diff


from .schemas import TOOLS


def call(name: str, arguments: dict[str, Any], policy: Policy) -> tuple[str, dict, bool]:
    """Run one tool. Returns (text, structured, is_error) and never raises."""
    handler = _HANDLERS.get(name)
    if handler is None:
        return f"Unknown tool: {name}", {}, True
    try:
        text, structured, is_error = handler(arguments or {}, policy)
    except Exception as exc:  # a tool error must not take the server down
        return f"{name} failed: {exc}", {}, True
    return _with_running_total(name, text, arguments, policy), structured, is_error


def _with_running_total(name: str, text: str, arguments: dict, policy: Policy) -> str:
    """Append the running total to every verdict the agent reads.

    Nobody runs a second command to find out whether the first was worth it, so
    the total rides along. Skipped for yieldpoint_stats, which is the total, and for
    errors, where a footer is noise on top of a problem.
    """
    if name == "yieldpoint_stats":
        return text
    from .. import ledger
    from ..report import running_line
    from ..totals import totals

    if not ledger.enabled(policy):
        return text
    line = running_line(totals(
        ledger.path_for(policy, arguments.get("root") or ".")
    ))
    return f"{text}\n\n{line}" if line else text


def _verify_change(arguments: dict, policy: Policy):
    from ..ledger import Timer

    before, after = arguments.get("before"), arguments.get("after")
    with Timer() as timer:
        verdict = verify_change(before, after, arguments.get("path", ""), policy)
    record_run(verdict, Run("mcp:verify_change",
                            len(before or "") + len(after or ""),
                            timer.elapsed_ms), policy)
    return _render(verdict), verdict.to_dict(), False


def _verify_diff(arguments: dict, policy: Policy):
    from ..ledger import Timer

    diff = arguments.get("diff", "")
    root = arguments.get("root") or "."
    with Timer() as timer:
        verdict = verify_diff(diff, root, policy)
    record_run(verdict, Run("mcp:verify_diff", len(diff), timer.elapsed_ms, root), policy)
    return _render(verdict), verdict.to_dict(), False


def _review(arguments: dict, policy: Policy):
    from ..worktree import uncommitted

    diff = uncommitted(
        arguments.get("root") or ".",
        staged=bool(arguments.get("staged")),
        against=arguments.get("against") or "",
    )
    if not diff.ok:
        # Not an error: "nothing to check" and "not a git repository" are both
        # ordinary answers, and returning is_error would make the agent retry.
        return diff.reason, {"status": "unverified", "reason": diff.reason}, False

    from ..ledger import Timer

    with Timer() as timer:
        verdict = verify_diff(diff.text, root=diff.root, policy=policy)
    record_run(verdict, Run("mcp:review", len(diff.text), timer.elapsed_ms,
                            diff.root), policy)

    # The agent asking this is mid-task; "should I commit now" is the other
    # half of the answer and it needs no extra work to produce.
    from ..harness.pacing import pace

    added = sum(1 for line in diff.text.splitlines()
                if line.startswith("+") and not line.startswith("+++"))
    files = len({line.split()[-1] for line in diff.text.splitlines()
                 if line.startswith("+++")})
    decision = pace(verdict, added, files, policy.structure.max_change_lines)
    structured = {**verdict.to_dict(), "pace": decision.to_dict()}
    text = f"{_render(verdict)}\n\npace: {decision.value} — {decision.reason}"
    return text, structured, False


def _scan(arguments: dict, policy: Policy):
    from ..scan import scan

    result = scan(arguments.get("path") or ".", policy)
    text = _render(result.verdict, header=f"{result.files} file(s) audited")
    return text, result.verdict.to_dict(), False


def _assess(arguments: dict, policy: Policy):
    from ..harness import Change, middleware

    change = Change(
        path=arguments.get("path", ""),
        before=arguments.get("before"),
        after=arguments.get("after"),
        task=arguments.get("task", ""),
    )
    result = middleware(policy).assess(change)
    text = (
        f"risk: {result['risk']['value']} — {result['risk']['reason']}\n"
        f"tier: {result['tier']['value']} — {result['tier']['reason']}\n"
        f"churn: {result['signals']['churn']} lines, "
        f"structural: {result['signals']['structural']}"
    )
    return text, result, False


def _stats(arguments: dict, policy: Policy):
    from .. import ledger
    from ..report import render, to_dict
    from ..stats import summarise

    root = arguments.get("root") or "."
    summary = summarise(ledger.load(ledger.path_for(policy, root)))
    return render(summary), to_dict(summary), False


def _brief(arguments: dict, policy: Policy) -> tuple[str, dict, bool]:
    """The pre-edit briefing. Reads files; makes no model call."""
    from ..brief import brief
    from ..briefing import render, to_dict

    paths = arguments.get("paths") or []
    if not paths:
        return "Name at least one path.", {}, True
    report = brief(paths, policy)
    return render(report), to_dict(report), False


def _policy(arguments: dict, policy: Policy):
    del arguments
    contract = policy.test_contract
    summary = {
        "project": policy.project_name,
        "source": policy.source,
        "protected_test_patterns": list(contract.protected_patterns),
        "rules": {
            "assertion_monotonicity": _name(contract.assertion_monotonicity),
            "vacuous_assertion": _name(contract.forbid_vacuous_assertions),
            "skip_marker": _name(contract.forbid_new_skip_markers),
            "disabled_assertion": _name(contract.forbid_swallowed_exceptions),
            "dangling_reference": _name(policy.refactor.dangling_reference),
            "export_removed": _name(policy.refactor.export_removed),
            "boundary_violation": _name(policy.boundaries.on_violation),
            "structure": _name(policy.structure.severity),
            "ci_check_removed": _name(policy.ci.check_removed),
            "ci_check_disabled": _name(policy.ci.check_disabled),
        },
        "limits": {
            "max_file_lines": policy.structure.max_file_lines,
            "max_function_lines": policy.structure.max_lines,
            "max_parameters": policy.structure.max_parameters,
            "max_complexity": policy.structure.max_complexity,
            "max_added_lines": policy.structure.max_added_lines,
        },
        "zones": [
            {"name": zone.name, "path": zone.path,
             "forbidden_imports": list(zone.forbidden_imports)}
            for zone in policy.boundaries.zones
        ],
    }
    return json.dumps(summary, indent=2), summary, False


def _render(verdict: Verdict, header: str = "") -> str:
    lines = [header] if header else []
    lines.append(f"verdict: {verdict.status.value}")
    if verdict.skipped:
        lines.append("not evaluated:")
        lines.extend(f"  - {note}" for note in verdict.skipped)
    if not verdict.findings:
        lines.append("No findings.")
        return "\n".join(lines)
    lines.append("")
    lines.append(verdict.prescription)
    return "\n".join(lines)


def _name(status) -> str:
    return status.value if status is not None else "off"


_HANDLERS: dict[str, Callable[[dict, Policy], tuple[str, dict, bool]]] = {
    "yieldpoint_verify_change": _verify_change,
    "yieldpoint_verify_diff": _verify_diff,
    "yieldpoint_review": _review,
    "yieldpoint_scan": _scan,
    "yieldpoint_assess": _assess,
    "yieldpoint_stats": _stats,
    "yieldpoint_brief": _brief,
    "yieldpoint_policy": _policy,
}
