"""Maintainability rules.

Deliberately *not* called SOLID enforcement. File length, function size,
parameter count, nesting, complexity, duplication and utility-dump modules are
decidable from the source. Liskov substitution and dependency inversion are not,
and a tool claiming to check them would be inflating vocabulary over substance
(RULES.md section 5). These are checkable proxies for maintainability, named as
what they are.

**Findings are differential by default.** A module that was already 500 lines is
not this change's fault, but growing it further is — so a violation is reported
only when the change introduced or worsened it. That lets the rules be switched
on in an existing repository without a wall of findings nobody caused, while
still ratcheting quality in the right direction. ``greenfield`` makes them
absolute, which is the right default for a project starting clean.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import glob
from .metrics import FunctionMetrics, ModuleMetrics, measure
from .verdict import Confidence, Finding, Status

FILE_TOO_LONG = "file_too_long"
FUNCTION_TOO_LONG = "function_too_long"
TOO_MANY_PARAMETERS = "too_many_parameters"
NESTING_TOO_DEEP = "nesting_too_deep"
COMPLEXITY_TOO_HIGH = "complexity_too_high"
UTILITY_MODULE = "utility_module"
DUPLICATE_IMPLEMENTATION = "duplicate_implementation"
CHANGE_TOO_LARGE = "change_too_large"

#: Fixture methods that frameworks define as per-class by convention.
#:
#: Two classes both writing ``def tearDown(self): self.tmp.cleanup()`` are not
#: duplicating an implementation — they are each declaring their own teardown,
#: which is what the framework asks for. "Extract the shared implementation"
#: here means introducing a base class, and that is a design decision about
#: test structure rather than a mechanical deduplication. Flagging it trains
#: people to skim past the rule, which costs more than the duplication does.
_FIXTURE_NAMES = frozenset({
    "setup", "teardown", "setupclass", "teardownclass",
    "setupmodule", "teardownmodule", "setup_method", "teardown_method",
    "setup_class", "teardown_class", "setup_function", "teardown_function",
    "asyncsetup", "asyncteardown", "setUpTestData",
})

#: Names that signal a module with no single responsibility.
_DUMP_NAMES = frozenset({"utils", "util", "helpers", "helper", "misc", "common", "shared"})


@dataclass(frozen=True)
class _Limit:
    rule: str
    attribute: str
    noun: str
    advice: str


_FUNCTION_LIMITS = (
    _Limit(FUNCTION_TOO_LONG, "lines", "lines",
           "Extract the distinct steps into named functions."),
    _Limit(TOO_MANY_PARAMETERS, "parameters", "parameters",
           "Group related parameters into a value object, or split the function."),
    _Limit(NESTING_TOO_DEEP, "nesting", "levels of nesting",
           "Return early, or extract the inner block into its own function."),
    _Limit(COMPLEXITY_TOO_HIGH, "complexity", "branches",
           "Split the decision into smaller functions, or replace the branching "
           "with a lookup."),
)


def check(before: str | None, after: str | None, path: str, config) -> tuple[list[Finding], list[str]]:
    """Apply the maintainability rules to one file."""
    if after is None or config.severity is None:
        return [], []

    now = measure(after, filename=path)
    if not now.ok:
        return [], [f"{path}: {now.error}"]
    was = measure(before or "", filename=path) if before is not None else ModuleMetrics()

    findings: list[Finding] = []
    findings.extend(_change_size(was, now, path, config))
    findings.extend(_module_rules(was, now, path, config))
    findings.extend(_function_rules(was, now, path, config))
    findings.extend(_duplicates(was, now, path, config))
    findings.extend(_custom(now, path, config))
    return findings, []


def _change_size(was, now, path, config) -> list[Finding]:
    """Cap how much one file may grow in a single change.

    Distinct from the file-length rule: a file can be well within its limit and
    still receive an unreviewable amount of new code at once. Reviewability is
    about the size of the *diff*, not the size of the result — an agent that
    emits a thousand lines in one step has produced something no one will read
    line by line, however well structured it is.
    """
    limit = config.max_added_lines
    if not limit:
        return []
    added = now.code_lines - was.code_lines
    if added <= limit:
        return []
    return [_finding(
        CHANGE_TOO_LARGE, config.severity, path, 1,
        f"This change adds {added} lines of code to {path}, over the limit of {limit}.",
        "Land it in smaller pieces that can each be reviewed and reverted on their "
        "own. A change this size is approved rather than read.",
    )]


def _module_rules(was, now, path, config) -> list[Finding]:
    findings = []
    limit = config.max_file_lines
    if limit and now.code_lines > limit and (config.greenfield or now.code_lines > was.code_lines):
        findings.append(_finding(
            FILE_TOO_LONG, config.severity, path, 1,
            f"{path} has {now.code_lines} lines of code, over the limit of {limit}.",
            "Split it into modules with one responsibility each. A file this size "
            "usually has more than one reason to change.",
        ))

    if config.forbid_utility_modules and (config.greenfield or not was.ok or was.lines == 0):
        stem = path.replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0]
        if stem.lower() in _DUMP_NAMES:
            findings.append(_finding(
                UTILITY_MODULE, config.severity, path, 1,
                f"`{stem}` is a catch-all module name.",
                "Name the module for its single responsibility. A utility dump "
                "accumulates unrelated code because nothing in the name excludes anything.",
            ))
    return findings


def _function_rules(was, now, path, config) -> list[Finding]:
    previous = {f.qualname: f for f in was.functions}
    findings = []
    for function in now.functions:
        old = previous.get(function.qualname)
        for limit in _FUNCTION_LIMITS:
            threshold = getattr(config, f"max_{limit.attribute}", None)
            value = getattr(function, limit.attribute)
            if not threshold or value <= threshold:
                continue
            if not config.greenfield and old is not None and value <= getattr(old, limit.attribute):
                continue  # already this bad, and not made worse here
            findings.append(_finding(
                limit.rule, config.severity, path, function.line,
                f"`{function.qualname}` has {value} {limit.noun}, over the limit "
                f"of {threshold}.",
                limit.advice, symbol=function.qualname,
            ))
    return findings


def _duplicates(was, now, path, config) -> list[Finding]:
    """Functions with identical structure — the DRY check.

    Compares shape rather than text, so a copy-paste that renamed its variables
    is still found. Short functions are excluded: two three-line accessors being
    identical is a coincidence, not duplication.
    """
    if config.duplicate_implementation is None:
        return []

    existing = _shape_pairs(was.functions)
    findings = []
    for shape, group in _shape_groups(now.functions).items():
        if len(group) < 2 or shape in existing:
            continue
        if all(_is_fixture(f) for f in group):
            continue
        first, *rest = group
        for duplicate in rest:
            findings.append(_finding(
                DUPLICATE_IMPLEMENTATION, config.duplicate_implementation, path,
                duplicate.line,
                f"`{duplicate.qualname}` is structurally identical to "
                f"`{first.qualname}` (line {first.line}).",
                "Extract the shared implementation. Two copies drift apart, and a "
                "fix applied to one is a bug left in the other.",
                symbol=duplicate.qualname,
            ))
    return findings


def _shape_groups(functions) -> dict[str, list[FunctionMetrics]]:
    groups: dict[str, list[FunctionMetrics]] = {}
    for function in functions:
        if function.substantial:
            groups.setdefault(function.shape, []).append(function)
    return groups


def _is_fixture(function) -> bool:
    """A framework fixture, which convention requires each class to repeat."""
    return function.name.replace("_", "").lower() in {
        name.replace("_", "").lower() for name in _FIXTURE_NAMES
    }


def _shape_pairs(functions) -> set[str]:
    return {shape for shape, group in _shape_groups(functions).items() if len(group) > 1}


def _custom(now, path, config) -> list[Finding]:
    """Project-defined rules, declared in configuration rather than in code."""
    findings = []
    for rule in config.custom:
        if rule.path and not glob.matches(rule.path, path):
            continue
        if rule.forbid_call and rule.forbid_call in now.calls:
            findings.append(_finding(
                rule.name, rule.severity, path, 1,
                rule.message or f"`{rule.forbid_call}` may not be called here.",
                rule.message or f"Remove the call to `{rule.forbid_call}`.",
            ))
        if rule.forbid_import:
            for module in now.imports:
                if module == rule.forbid_import or module.startswith(f"{rule.forbid_import}."):
                    findings.append(_finding(
                        rule.name, rule.severity, path, 1,
                        rule.message or f"`{module}` may not be imported here.",
                        rule.message or f"Remove the import of `{module}`.",
                    ))
                    break
        if rule.require_name_pattern:
            pattern = re.compile(rule.require_name_pattern)
            for function in now.functions:
                if "." not in function.qualname and not pattern.search(function.name):
                    findings.append(_finding(
                        rule.name, rule.severity, path, function.line,
                        rule.message
                        or f"`{function.name}` does not match {rule.require_name_pattern}.",
                        f"Rename it to match `{rule.require_name_pattern}`.",
                        symbol=function.qualname,
                    ))
    return findings


def _finding(rule, status, path, line, detail, prescription, symbol=None) -> Finding:
    return Finding(
        rule=rule, status=status, file=path, line=line, detail=detail,
        prescription=prescription, symbol=symbol, confidence=Confidence.EXACT,
    )
