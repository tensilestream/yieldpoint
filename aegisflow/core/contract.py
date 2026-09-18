"""The test-contract rules.

Assertion monotonicity plus the integrity checks, applied only to files the
policy marks as protected tests. Separated from verify.py so that the entry
point stays a thin composition of independent rule sets — and so neither file
outgrows the 300-line limit in RULES.md section 1.
"""

from __future__ import annotations

from . import monotonicity, testintegrity
from .assertions import extract
from .policy import Policy
from .verdict import Confidence, Finding, Verdict

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


def check(before, after, path, policy, also_covered) -> Verdict:
    """The assertion-integrity rules, which apply only to protected test files."""
    if not policy.protects(path):
        # No test-contract rule applies. Saying "checked" here would let a file
        # nothing examined look like one that passed (RULES.md section 5).
        return Verdict.of([])

    if not path.endswith(EXACT_SUFFIXES):
        return Verdict.of([], skipped=[f"{path}: no exact analyser for this language yet"])

    before_state = extract(before or "", filename=path)
    after_state = extract(after or "", filename=path)

    for state, label in ((before_state, "before"), (after_state, "after")):
        if not state.ok:
            return Verdict.of([], skipped=[f"{path}: {label} state unparseable — {state.error}"])

    findings: list[Finding] = []
    findings.extend(_monotonicity(before_state, after_state, path, policy, also_covered))
    findings.extend(_integrity(before_state, after_state, path, policy))
    return Verdict.of(findings, checked=[path])


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
        for weakening in monotonicity.compare(
            before, after, also_covered=also_covered,
            accessors=policy.subjects.accessor_equivalence,
        )
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


def deduplicate(findings: list[Finding]) -> list[Finding]:
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
