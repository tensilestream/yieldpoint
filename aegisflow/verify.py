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
from .core.linters import registry, runner
from .core.linters.adapter import FAST
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
    findings: list[Finding] = []
    checked: list[str] = []
    skipped: list[str] = []

    lint_findings, lint_skipped = _lint(after, path, resolved)
    findings.extend(lint_findings)
    skipped.extend(lint_skipped)

    contract = _test_contract(before, after, path, resolved, also_covered)
    findings.extend(contract.findings)
    checked.extend(contract.checked)
    skipped.extend(contract.skipped)

    if not checked and not skipped:
        checked.append(path)
    return Verdict.of(_deduplicate(findings), checked=checked, skipped=skipped)


def _test_contract(before, after, path, policy, also_covered) -> Verdict:
    """The assertion-integrity rules, which apply only to protected test files."""
    if not policy.protects(path):
        return Verdict.of([], checked=[path])

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


def _lint(after: str | None, path: str, policy: Policy) -> tuple[list[Finding], list[str]]:
    """Run the project's own linters, if the project asked for them.

    Findings are ``Confidence.EXTERNAL``: reproducible for a given tool version,
    but the version is an environment read, so they advise and never block.
    """
    config = policy.linters
    if not config.enabled or not config.tools or after is None or config.severity is None:
        return [], []

    findings: list[Finding] = []
    skipped: list[str] = []
    for adapter in registry.for_path(path, config.tools):
        if adapter.cost != FAST and not config.include_slow:
            skipped.append(f"{path}: {adapter.name} skipped (slow; set linters.include_slow)")
            continue
        result = runner.run(adapter, path, after, timeout=config.timeout_seconds)
        if not result.ran:
            skipped.append(f"{path}: {adapter.name} — {result.skipped}")
            continue
        for item in result.findings:
            findings.append(
                Finding(
                    rule=_lint_rule(item),
                    status=config.severity,
                    file=path,
                    line=item.line,
                    detail=item.message,
                    prescription=_lint_prescription(adapter, item),
                    confidence=Confidence.EXTERNAL,
                )
            )
    return findings, skipped


def _lint_rule(item) -> str:
    """``lint.ruff.F401``, without repeating a tool name the code already carries."""
    code = item.code if not item.code.startswith(item.tool) else item.code[len(item.tool):]
    code = code.strip(".") or item.tool
    return f"lint.{item.tool}.{code}"


def _lint_prescription(adapter, item) -> str:
    if adapter.fix_hint:
        suffix = " This is auto-fixable." if item.fixable else ""
        return f"Run `{adapter.fix_hint}`.{suffix}"
    return f"Resolve the {adapter.name} diagnostic before writing."


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
