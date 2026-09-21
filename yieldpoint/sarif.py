"""Findings in the format code-review platforms already read.

The one output in this package not written for a person or an agent. GitHub
and GitLab both ingest SARIF and turn it into inline annotations on a pull
request, which makes this the only thing Yieldpoint produces that is seen by
people who did not choose to install it. That is what carries a tool past the
engineer who set it up.

Severity is mapped conservatively. A platform annotation that says *error* is a
claim the change is wrong, and only a finding this package can prove — one at
``Confidence.EXACT`` that gates — earns it. Everything lexical or external
becomes a note, whatever its configured severity, because a linter that shouts
at the same volume as a compiler gets muted along with its useful half.
"""

from __future__ import annotations

import hashlib
import json

from .core.verdict import Confidence, Status

SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
VERSION = "2.1.0"
HOME = "https://github.com/tensilestream/yieldpoint"

#: SARIF's three levels that render as annotations. ``none`` renders as nothing,
#: which would make a finding invisible rather than quiet.
ERROR, WARNING, NOTE = "error", "warning", "note"

_GATING = {Status.BLOCK, Status.ESCALATE}


def level_for(finding, advisory: bool = False) -> str:
    """How loudly a platform should say this.

    ``advisory`` is true for findings the policy reports but does not enforce —
    shape rules, chiefly. A platform has no idea which of our rules can stop a
    merge, so the caller says which ones cannot.
    """
    if advisory or finding.confidence is not Confidence.EXACT:
        return NOTE
    return ERROR if finding.status in _GATING else WARNING


def fingerprint(finding) -> str:
    """A stable identity for this finding across runs.

    Deliberately excludes the line number: a finding that moved because
    something above it changed is the same finding, and a platform that treats
    it as new re-notifies everybody on every commit.
    """
    parts = f"{finding.rule}|{finding.file}|{finding.symbol or ''}"
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()[:16]


def _rule(rule: str) -> dict:
    return {
        "id": rule,
        "name": rule,
        "shortDescription": {"text": rule.replace("_", " ")},
        "helpUri": f"{HOME}/blob/main/docs/rules.html#{rule}",
    }


def _result(finding, advisory: bool) -> dict:
    return {
        "ruleId": finding.rule,
        "level": level_for(finding, advisory),
        "message": {"text": f"{finding.detail} {finding.prescription}".strip()},
        "partialFingerprints": {"yieldpointFindingV1": fingerprint(finding)},
        "locations": [{"physicalLocation": {
            "artifactLocation": {"uri": finding.file},
            "region": {"startLine": max(1, finding.line)},
        }}],
    }


def _notification(note: str) -> dict:
    """A file nothing could analyse, reported rather than left as a gap.

    SARIF carries these apart from results, which is exactly right: "no rule
    could read this" is not a finding about the code and must not be counted
    as one (RULES.md section 5).
    """
    return {"level": NOTE, "message": {"text": note},
            "descriptor": {"id": "not_evaluated"}}


def build(verdict, *, advisory=(), version: str = "") -> dict:
    """One SARIF run. ``advisory`` names the rules that cannot stop a merge."""
    findings = list(verdict.findings)
    return {
        "$schema": SCHEMA,
        "version": VERSION,
        "runs": [{
            "tool": {"driver": {
                "name": "Yieldpoint",
                "informationUri": HOME,
                **({"version": version} if version else {}),
                "rules": [_rule(r) for r in sorted({f.rule for f in findings})],
            }},
            "invocations": [{
                "executionSuccessful": True,
                "toolExecutionNotifications": [
                    _notification(note) for note in verdict.skipped],
            }],
            "results": [_result(f, f.rule in advisory) for f in findings],
        }],
    }


def dumps(verdict, *, advisory=(), version: str = "") -> str:
    return json.dumps(build(verdict, advisory=advisory, version=version), indent=2)


def advisory_rules(policy) -> frozenset[str]:
    """Which rules this policy reports without enforcing.

    Read from the policy rather than assumed: a project that sets
    ``structure.gates`` has decided its shape rules do stop a merge, and a
    SARIF run that still called them notes would misreport that project's own
    decision back to it.
    """
    from .core.policychange import POLICY_WEAKENED
    from .core.structure import MAINTAINABILITY_RULES

    if policy.structure.gates:
        return frozenset({POLICY_WEAKENED})
    return MAINTAINABILITY_RULES | {POLICY_WEAKENED}


__all__ = ["build", "dumps", "level_for", "fingerprint", "advisory_rules"]
