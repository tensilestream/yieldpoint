"""The verification entry point.

``verify_change`` is the core primitive: given the before and after content of
one file, return a :class:`Verdict`. Everything else — the CLI, the Claude Code
hook, the LangGraph node, a future MCP server — is a translation layer over this
one call.

Policy decides severity; this module decides only whether a rule fired. A file
that cannot be analysed is recorded in ``skipped`` and never counted as passing
(RULES.md section 5).
"""

from __future__ import annotations

from typing import Mapping

from .core import monotonicity, testintegrity
from .core.assertions import extract
from .core.policy import Policy
from .core.relation import Relation
from .core.verdict import Confidence, Finding, Status, Verdict

ASSERTION_MONOTONICITY = "assertion_monotonicity"

#: Only Python is analysed exactly today. Other languages are reported as
#: skipped rather than silently passed; see IMPLEMENTATION_STAGES.md.
EXACT_SUFFIXES = (".py",)

_OFFENCE_POLICY = {
    testintegrity.VACUOUS_ASSERTION: "forbid_vacuous_assertions",
    testintegrity.EMPTY_TEST: "forbid_vacuous_assertions",
    testintegrity.SKIP_MARKER: "forbid_new_skip_markers",
    testintegrity.DISABLED_ASSERTION: "forbid_swallowed_exceptions",
}


def verify_change(
    before: str | None,
    after: str | None,
    path: str,
    policy: Policy | str | dict | None = None,
    *,
    also_covered: Mapping[str, Relation] | None = None,
) -> Verdict:
    """Verify one file's transition from ``before`` to ``after``.

    ``before`` is ``None`` for a newly created file and ``after`` is ``None`` for
    a deleted one. ``also_covered`` carries subjects verified elsewhere in the
    same change set, so relocating a test is not reported as loss.
    """
    resolved = Policy.load(policy)

    if not resolved.protects(path):
        # Not a protected test file: the test contract does not apply.
        return Verdict.of([], checked=[path])

    if not path.endswith(EXACT_SUFFIXES):
        return Verdict.of([], skipped=[f"{path}: no exact analyser for this language yet"])

    before_state = extract(before or "", filename=path)
    after_state = extract(after or "", filename=path)

    for state, label in ((before_state, "before"), (after_state, "after")):
        if not state.ok:
            return Verdict.of([], skipped=[f"{path}: {label} state unparseable — {state.error}"])

    findings: list[Finding] = []
    findings.extend(_monotonicity(before_state, after_state, path, resolved, also_covered))
    findings.extend(_integrity(before_state, after_state, path, resolved))
    return Verdict.of(_deduplicate(findings), checked=[path])


def _monotonicity(before, after, path, policy, also_covered) -> list[Finding]:
    status = policy.test_contract.assertion_monotonicity
    if status is None:
        return []
    return [
        Finding(
            rule=ASSERTION_MONOTONICITY,
            status=status,
            file=path,
            line=weakening.line,
            detail=weakening.detail,
            prescription=weakening.prescription,
            before=weakening.source or None,
            symbol=weakening.test or None,
            confidence=Confidence.EXACT,
        )
        for weakening in monotonicity.compare(before, after, also_covered=also_covered)
    ]


def _integrity(before, after, path, policy) -> list[Finding]:
    findings: list[Finding] = []
    for offence in testintegrity.compare(before, after):
        attribute = _OFFENCE_POLICY.get(offence.rule)
        status = getattr(policy.test_contract, attribute, None) if attribute else None
        if status is None:
            continue
        findings.append(
            Finding(
                rule=offence.rule,
                status=status,
                file=path,
                line=offence.line,
                detail=offence.detail,
                prescription=offence.prescription,
                before=offence.source or None,
                symbol=offence.test or None,
                confidence=Confidence.EXACT,
            )
        )
    return findings


def _deduplicate(findings: list[Finding]) -> list[Finding]:
    """Drop subject-level findings for a test already reported as emptied.

    Emptying a test body removes every assertion in it; reporting the empty body
    *and* each lost subject says the same thing several times, and a prescription
    an agent has to deduplicate is a worse prescription.
    """
    emptied = {
        f.symbol for f in findings if f.rule == testintegrity.EMPTY_TEST and f.symbol
    }
    if not emptied:
        return findings
    return [
        f for f in findings
        if not (f.rule == ASSERTION_MONOTONICITY and f.symbol in emptied)
    ]
