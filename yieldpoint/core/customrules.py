"""Rules a project declares in its own configuration.

Split from structure.py because the two change for different reasons: that
file when Yieldpoint learns a new rule, this one when a project needs to
express a rule Yieldpoint does not have. Keeping them apart also keeps the
built-in rules readable — a reader looking for what the tool enforces by
default should not have to step over the machinery for what a team added.

Imports ``_finding`` from structure rather than redefining it. structure
imports this module lazily, inside ``check``, so the pair does not form an
import cycle.
"""

from __future__ import annotations

import re

from . import glob
from .structure import _finding
from .verdict import Finding


def _forbidden_call(rule, now, path: str) -> list[Finding]:
    if not rule.forbid_call or rule.forbid_call not in now.calls:
        return []
    return [_finding(
        rule.name, rule.severity, path, 1,
        rule.message or f"`{rule.forbid_call}` may not be called here.",
        rule.message or f"Remove the call to `{rule.forbid_call}`.",
    )]


def _forbidden_import(rule, now, path: str) -> list[Finding]:
    """The first matching import only: one finding per rule, not per line.

    A module that imports a forbidden package four times has one problem.
    """
    for module in now.imports:
        if module == rule.forbid_import or module.startswith(f"{rule.forbid_import}."):
            return [_finding(
                rule.name, rule.severity, path, 1,
                rule.message or f"`{module}` may not be imported here.",
                rule.message or f"Remove the import of `{module}`.",
            )]
    return []


def _misnamed(rule, now, path: str) -> list[Finding]:
    """Top-level functions only — a method's name is constrained by its class."""
    pattern = re.compile(rule.require_name_pattern)
    return [_finding(
        rule.name, rule.severity, path, function.line,
        rule.message or f"`{function.name}` does not match {rule.require_name_pattern}.",
        f"Rename it to match `{rule.require_name_pattern}`.",
        symbol=function.qualname,
    ) for function in now.functions
        if "." not in function.qualname and not pattern.search(function.name)]


def _applies(rule, path: str) -> bool:
    return not rule.path or glob.matches(rule.path, path)


def custom(now, path: str, config) -> list[Finding]:
    """Every configured rule that applies to this file."""
    findings: list[Finding] = []
    for rule in config.custom:
        if not _applies(rule, path):
            continue
        findings.extend(_forbidden_call(rule, now, path))
        if rule.forbid_import:
            findings.extend(_forbidden_import(rule, now, path))
        if rule.require_name_pattern:
            findings.extend(_misnamed(rule, now, path))
    return findings


__all__ = ["custom"]
