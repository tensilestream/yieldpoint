"""Turning external tool output into findings.

Kept with the linters rather than in verify.py because it changes when a tool's
output does, not when the verification rules do — and because verify.py is close
to the 300-line limit in RULES.md section 1.

Findings here carry ``Confidence.EXTERNAL``: reproducible for a given tool
version, but the version is an environment read, so they advise and never block.
"""

from __future__ import annotations

from ..policy import Policy
from ..verdict import Confidence, Finding
from . import registry, runner
from .adapter import FAST


def collect(after: str | None, path: str, policy: Policy) -> tuple[list[Finding], list[str]]:
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
                    rule=rule_for(item),
                    status=config.severity,
                    file=path,
                    line=item.line,
                    detail=item.message,
                    prescription=prescription_for(adapter, item),
                    confidence=Confidence.EXTERNAL,
                )
            )
    return findings, skipped


def rule_for(item) -> str:
    """``lint.ruff.F401``, without repeating a tool name the code already carries."""
    code = item.code if not item.code.startswith(item.tool) else item.code[len(item.tool):]
    code = code.strip(".") or item.tool
    return f"lint.{item.tool}.{code}"


def prescription_for(adapter, item) -> str:
    if adapter.fix_hint:
        suffix = " This is auto-fixable." if item.fixable else ""
        return f"Run `{adapter.fix_hint}`.{suffix}"
    return f"Resolve the {adapter.name} diagnostic before writing."
