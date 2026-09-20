"""The test-contract rules.

Assertion monotonicity plus the integrity checks, applied only to files the
policy marks as protected tests. Separated from verify.py so that the entry
point stays a thin composition of independent rule sets — and so neither file
outgrows the 300-line limit in RULES.md section 1.
"""

from __future__ import annotations

from . import lexical, monotonicity, testintegrity
from .relation import Relation
from .assertions import Extraction, extract
from .policy import Policy
from .verdict import Confidence, Finding, Status, Verdict

ASSERTION_MONOTONICITY = "assertion_monotonicity"

#: Only Python is analysed exactly today. Other languages are reported as
#: skipped rather than silently passed.
EXACT_SUFFIXES = (".py",)

_OFFENCE_POLICY = {
    testintegrity.VACUOUS_ASSERTION: "forbid_vacuous_assertions",
    testintegrity.EMPTY_TEST: "forbid_vacuous_assertions",
    testintegrity.WEAK_NEW_TEST: "forbid_weak_new_tests",
    testintegrity.SKIP_MARKER: "forbid_new_skip_markers",
    testintegrity.DISABLED_ASSERTION: "forbid_swallowed_exceptions",
}


def check(before, after, path, policy, also_covered) -> Verdict:
    """The assertion-integrity rules, which apply only to protected test files."""
    if not policy.protects(path):
        # No test-contract rule applies. Saying "checked" here would let a file
        # nothing examined look like one that passed (RULES.md section 5).
        return Verdict.of([])

    if path.endswith(EXACT_SUFFIXES):
        return _exactly(before, after, path, policy, also_covered)
    if lexical.reads(path):
        return _lexically(before, after, path, policy, also_covered)
    return Verdict.of([], skipped=[f"{path}: no analyser for this language yet"])


def _exactly(before, after, path, policy, also_covered) -> Verdict:
    """The Python path: parsed, and therefore permitted to block."""
    before_state = extract(before or "", filename=path)
    after_state = extract(after or "", filename=path)

    for state, label in ((before_state, "before"), (after_state, "after")):
        if not state.ok:
            return Verdict.of([], skipped=[f"{path}: {label} state unparseable — {state.error}"])

    findings: list[Finding] = []
    findings.extend(_monotonicity(before_state, after_state, path, policy, also_covered))
    findings.extend(_integrity(before_state, after_state, path, policy))
    return Verdict.of(findings, checked=[path])


def _lexically(before, after, path, policy, also_covered) -> Verdict:
    """Languages read by shape rather than by parsing.

    Monotonicity runs, and so do ``empty_test``, ``skip_marker`` and
    ``vacuous_assertion``. Only ``disabled_assertion`` stays behind: it asks
    whether a failure can propagate, which means knowing control flow, and
    guessing at control flow from braces is how a checker starts accusing
    people of things they did not do.

    The other three need no control flow at all. A body with nothing between
    its braces, an annotation that switches a test off, and an assertion whose
    subject is a literal are each unambiguous in every language here. Keeping
    them Python-only reached one language of twelve for a reason that never
    applied to them.

    A file where nothing was recognised is reported as **unverified**, never as
    clean: silence from an analyser that did not understand the input must not
    read as approval (RULES.md section 5).
    """
    before_tests, before_ok = lexical.extract(before or "", filename=path)
    after_tests, after_ok = lexical.extract(after or "", filename=path)

    if not (before_ok or after_ok):
        return Verdict.of([], skipped=[
            f"{path}: read lexically, but no test assertions were recognised"
        ])

    findings = _monotonicity(
        _as_extraction(before_tests), _as_extraction(after_tests),
        path, policy, also_covered, confidence=Confidence.LEXICAL,
    )
    findings.extend(_emptied(before_tests, after_tests, path, policy))
    findings.extend(_skipped(before_tests, after_tests, path, policy))
    findings.extend(_vacuous(before_tests, after_tests, path, policy))
    return Verdict.of(findings, checked=[path])


def _advisory(status):
    """A finding not derived from a parse may not stop anyone's work, so a
    policy asking for ``block`` degrades here rather than raising."""
    return Status.ESCALATE if status is Status.BLOCK else status


def _emptied(before_tests, after_tests, path, policy) -> list[Finding]:
    """Tests this change left with nothing in them. Differential."""
    status = policy.test_contract.forbid_vacuous_assertions
    if status is None:
        return []
    already = {t.qualname for t in before_tests if t.is_empty}
    return [
        Finding(
            rule=testintegrity.EMPTY_TEST, status=_advisory(status), file=path,
            line=test.line,
            detail=f"{test.qualname} has no body and verifies nothing.",
            prescription=f"Give {test.qualname} assertions, or remove it.",
            symbol=test.qualname, confidence=Confidence.LEXICAL,
        )
        for test in after_tests
        if test.is_empty and test.qualname not in already
    ]


def _skipped(before_tests, after_tests, path, policy) -> list[Finding]:
    """Tests this change switched off. A marker is a shape, not control flow."""
    status = policy.test_contract.forbid_new_skip_markers
    if status is None:
        return []
    already = {t.qualname for t in before_tests if t.skip_markers}
    return [
        Finding(
            rule=testintegrity.SKIP_MARKER, status=_advisory(status), file=path,
            line=test.line,
            detail=f"{test.qualname} is skipped ({', '.join(test.skip_markers)}).",
            prescription=(
                f"Remove the skip marker from {test.qualname} and make it pass, "
                "or delete the test deliberately rather than disabling it."
            ),
            before=", ".join(test.skip_markers),
            symbol=test.qualname, confidence=Confidence.LEXICAL,
        )
        for test in after_tests
        if test.skip_markers and test.qualname not in already
    ]


def _vacuous(before_tests, after_tests, path, policy) -> list[Finding]:
    """Assertions that cannot fail because nothing about the code is in them."""
    status = policy.test_contract.forbid_vacuous_assertions
    if status is None:
        return []
    already = {
        (t.qualname, a.subject) for t in before_tests for a in t.assertions
        if a.relation is Relation.VACUOUS
    }
    return [
        Finding(
            rule=testintegrity.VACUOUS_ASSERTION, status=_advisory(status),
            file=path, line=assertion.line,
            detail=f"`{assertion.raw}` is a tautology and can never fail.",
            prescription=(
                "Assert something about the value under test, or delete the "
                "line. A tautology makes the suite green without verifying "
                "anything."
            ),
            before=assertion.raw or None,
            symbol=test.qualname, confidence=Confidence.LEXICAL,
        )
        for test in after_tests for assertion in test.assertions
        if assertion.relation is Relation.VACUOUS
        and (test.qualname, assertion.subject) not in already
    ]


def _as_extraction(tests) -> Extraction:
    return Extraction(tests=tuple(tests), by_name={t.qualname: t for t in tests})


def _monotonicity(before, after, path, policy, also_covered,
                  confidence: Confidence = Confidence.EXACT) -> list[Finding]:
    status = policy.test_contract.assertion_monotonicity
    if status is None:
        return []
    # A finding that was not derived from a parse may not stop anyone's work.
    # Enforced in Finding.__post_init__ too; capped here so configuring
    # `block` on a lexical language degrades instead of raising.
    if not confidence.may_block and status is Status.BLOCK:
        status = Status.ESCALATE
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
            confidence=confidence,
            kind=weakening.kind,
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
