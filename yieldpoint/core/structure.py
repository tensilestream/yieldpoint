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

from dataclasses import dataclass

from . import glob
from .baseline import CARRIED, IMPROVING, INHERITED_NOTE, WORSENED, Baseline
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

#: Every rule in this module. These describe the *shape* of code — how long, how
#: nested, how large a diff — and none of them is a statement that the change
#: took something away. Naming the set here, beside where they are emitted, is
#: what lets a caller report them without letting them stop a commit.
MAINTAINABILITY_RULES = frozenset({
    "sibling_module_shadows_package",
    FILE_TOO_LONG, FUNCTION_TOO_LONG, TOO_MANY_PARAMETERS, NESTING_TOO_DEEP,
    COMPLEXITY_TOO_HIGH, UTILITY_MODULE, DUPLICATE_IMPLEMENTATION, CHANGE_TOO_LARGE,
})

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


def excluded(path: str, config) -> bool:
    """Is this file exempt from the maintainability limits?

    Matched as globs, so a directory, an exact filename and an extension are
    all expressible. Generated code, vendored trees and migrations are the
    cases this exists for: files nobody chose the shape of.
    """
    from . import glob

    return bool(config.exclude) and glob.matches_any(config.exclude, path)


def check(before: str | None, after: str | None, path: str, config) -> tuple[list[Finding], list[str]]:
    """Apply the maintainability rules to one file.

    Exclusions are honoured here and nowhere else: a file exempt from the
    length limit is still checked for a weakened test contract. Letting a path
    switch that off would make the contract optional, which is the one thing
    it must not be.
    """
    if after is None or config.severity is None:
        return [], []
    if excluded(path, config):
        return [], []

    now = measure(after, filename=path)
    if not now.ok:
        return [], [f"{path}: {now.error}"]
    was = measure(before or "", filename=path) if before is not None else ModuleMetrics()

    findings: list[Finding] = []
    findings.extend(_change_size(was, now, path, config))
    findings.extend(_module_rules(was, now, path, config, before is not None))
    findings.extend(_function_rules(was, now, path, config, before is not None))
    findings.extend(_duplicates(was, now, path, config))
    from .customrules import custom

    findings.extend(custom(now, path, config))
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


#: What to do about a file already over the limit before this change. Telling
#: someone to split a 1,400-line module because they added a line is advice
#: they cannot act on inside the task they were given, and unactionable advice
#: is how an escape hatch becomes a reflex.
_INHERITED = ("Splitting it is owed, but it is not this change's debt. Keep this "
              "change from adding to it, or acknowledge the growth with a reason.")

_SPLIT = ("Split it into modules with one responsibility each. A file this size "
          "usually has more than one reason to change.")


def _file_length(now, path, config, before: int | None) -> list[Finding]:
    """The file-length rule, attributing the count to whoever earned it."""
    state = Baseline(now.code_lines, config.max_file_lines or 0, before)
    if not state.over or state.classification in (CARRIED, IMPROVING):
        return []
    return [_finding(
        FILE_TOO_LONG, config.severity, path, 1,
        state.describe(path, "lines of code"),
        _INHERITED if state.classification == WORSENED else _SPLIT,
    )]


def _module_rules(was, now, path, config, known: bool = True) -> list[Finding]:
    # Greenfield declares the project starts clean, so everything over a limit
    # is the project's own — the same shape as a baseline of zero.
    before = 0 if config.greenfield else (was.code_lines if known else None)
    findings = _file_length(now, path, config, before)

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


def _function_rules(was, now, path, config, known: bool = True) -> list[Finding]:
    previous = {f.qualname: f for f in was.functions}
    findings = []
    for function in now.functions:
        old = previous.get(function.qualname)
        for limit in _FUNCTION_LIMITS:
            threshold = getattr(config, f"max_{limit.attribute}", None)
            value = getattr(function, limit.attribute)
            state = Baseline(value, threshold or 0,
                             _before(old, limit.attribute, config, known))
            if not state.over or state.classification in (CARRIED, IMPROVING):
                continue  # within the limit, or already this bad and not worsened here
            findings.append(_finding(
                limit.rule, config.severity, path, function.line,
                state.describe(f"`{function.qualname}`", limit.noun),
                limit.advice + (f" {INHERITED_NOTE}"
                                if state.classification == WORSENED else ""),
                symbol=function.qualname,
            ))
    return findings


def _before(old, attribute: str, config, known: bool) -> int | None:
    """This function's measure at the baseline, or nothing if there is none.

    A function absent from the baseline was written by this change, which is a
    baseline of zero. A function absent because there *is* no baseline is a
    different fact and must not be reported as though this change wrote it.
    """
    if config.greenfield:
        return 0
    if old is not None:
        return getattr(old, attribute)
    return 0 if known else None


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


def _finding(rule, status, path, line, detail, prescription, symbol=None) -> Finding:
    return Finding(
        rule=rule, status=status, file=path, line=line, detail=detail,
        prescription=prescription, symbol=symbol, confidence=Confidence.EXACT,
    )
