"""Reading a policy document into the policy model.

Split from policy.py so that the model (what a rule *is*) and the reader (how a
JSON document becomes one) change independently — and so neither file outgrows
the 300-line limit in RULES.md section 1.

Malformed configuration degrades with a warning rather than raising: a policy
file that a newer AegisFlow wrote, or that someone typo'd, must not stop an agent
from working.
"""

from __future__ import annotations

from typing import Any

from .policy import (
    DEFAULT_PROTECTED_PATTERNS,
    Boundaries,
    GeneratedCode,
    Linters,
    LoopBreaker,
    Policy,
    TestContract,
    Voice,
    Zone,
)
from .verdict import Status


def read(raw: dict[str, Any], *, source_name: str = "<dict>") -> Policy:
    """Normalise a parsed `.aegisflow.json` document into a :class:`Policy`."""
    warnings: list[str] = []
    project = _section(raw, "project", warnings)
    contract = _section(raw, "test_contract", warnings)
    boundaries = _section(raw, "boundaries", warnings)
    breaker = _section(raw, "loop_breaker", warnings)
    linters = _section(raw, "linters", warnings)
    voice = _section(raw, "voice", warnings)
    generated = _section(raw, "generated", warnings)

    patterns = _str_tuple(contract.get("protected_patterns"), warnings, "protected_patterns")

    return Policy(
        version=str(raw.get("version", "1.0")),
        project_name=str(project.get("name", "unnamed")),
        languages=_str_tuple(project.get("languages"), warnings, "languages") or ("python",),
        test_contract=TestContract(
            protected_patterns=patterns or DEFAULT_PROTECTED_PATTERNS,
            assertion_monotonicity=_status(
                contract.get("assertion_monotonicity"), Status.REPAIR, warnings,
                "assertion_monotonicity"),
            forbid_vacuous_assertions=_status(
                contract.get("forbid_vacuous_assertions"), Status.REPAIR, warnings,
                "forbid_vacuous_assertions"),
            forbid_new_skip_markers=_status(
                contract.get("forbid_new_skip_markers"), Status.REPAIR, warnings,
                "forbid_new_skip_markers"),
            forbid_swallowed_exceptions=_status(
                contract.get("forbid_swallowed_exceptions"), Status.REPAIR, warnings,
                "forbid_swallowed_exceptions"),
        ),
        boundaries=Boundaries(
            on_violation=_status(
                boundaries.get("on_violation"), Status.REPAIR, warnings, "on_violation"),
            zones=_zones(boundaries.get("zones"), warnings),
        ),
        loop_breaker=LoopBreaker(
            window=_int(breaker.get("window"), 6, warnings, "window"),
            max_repeats_without_progress=_int(
                breaker.get("max_repeats_without_progress"), 3, warnings,
                "max_repeats_without_progress"),
            on_trip=_status(breaker.get("on_trip"), Status.ESCALATE, warnings, "on_trip"),
        ),
        linters=_linters(linters, warnings),
        voice=Voice(
            severity_floor=_status(
                voice.get("severity_floor"), Status.ESCALATE, warnings, "voice.severity_floor"),
            max_spoken_findings=_int(
                voice.get("max_spoken_findings"), 3, warnings, "voice.max_spoken_findings"),
            confirm_on_removals=_int(
                voice.get("confirm_on_removals"), 2, warnings, "voice.confirm_on_removals"),
        ),
        generated=GeneratedCode(
            detect=bool(generated.get("detect", True)),
            on_hand_edit=_status(
                generated.get("on_hand_edit"), Status.REPAIR, warnings,
                "generated.on_hand_edit"),
            extra_patterns=_str_tuple(
                generated.get("extra_patterns"), warnings, "generated.extra_patterns"),
        ),
        source=source_name,
        warnings=tuple(warnings),
    )

def _section(raw: dict[str, Any], key: str, warnings: list[str]) -> dict[str, Any]:
    value = raw.get(key, {})
    if isinstance(value, dict):
        return value
    warnings.append(f"{key!r} must be an object; ignoring {type(value).__name__}.")
    return {}


def _status(value: Any, default: Status | None, warnings: list[str], label: str) -> Status | None:
    if value is None:
        return default
    if value is False or (isinstance(value, str) and value.lower() == "off"):
        return None
    if value is True:
        return default
    try:
        return Status(str(value).lower())
    except ValueError:
        allowed = ", ".join(s.value for s in Status) + ", off"
        warnings.append(f"{label}: {value!r} is not one of [{allowed}]; using {default}.")
        return default


def _int(value: Any, default: int, warnings: list[str], label: str) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        warnings.append(f"{label}: {value!r} is not an integer; using {default}.")
        return default
    if parsed < 1:
        warnings.append(f"{label}: must be >= 1, got {parsed}; using {default}.")
        return default
    return parsed


def _str_tuple(value: Any, warnings: list[str], label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        warnings.append(f"{label}: expected a list; ignoring.")
        return ()
    return tuple(str(item) for item in value)


def _linters(raw: dict[str, Any], warnings: list[str]) -> Linters:
    from .linters import registry

    requested = _str_tuple(raw.get("tools"), warnings, "linters.tools")
    known, unknown = [], []
    for name in requested:
        (known if registry.get(name) else unknown).append(name)
    if unknown:
        warnings.append(
            f"linters.tools: unknown tool(s) {', '.join(sorted(unknown))}; "
            f"available: {', '.join(registry.names())}"
        )

    severity = _status(raw.get("severity"), Status.REPAIR, warnings, "linters.severity")
    if severity is Status.BLOCK:
        # An external tool's verdict depends on its installed version, so it is
        # never authoritative enough to stop work outright.
        warnings.append("linters.severity: 'block' is not permitted; using 'escalate'.")
        severity = Status.ESCALATE

    return Linters(
        enabled=bool(raw.get("enabled", False)),
        severity=severity,
        timeout_seconds=_int(raw.get("timeout_seconds"), 10, warnings, "linters.timeout_seconds"),
        include_slow=bool(raw.get("include_slow", False)),
        tools=tuple(known),
    )


def _zones(value: Any, warnings: list[str]) -> tuple[Zone, ...]:
    if not isinstance(value, list):
        if value is not None:
            warnings.append("boundaries.zones: expected a list; ignoring.")
        return ()
    zones: list[Zone] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict) or not item.get("path"):
            warnings.append(f"boundaries.zones[{index}]: missing 'path'; ignoring.")
            continue
        zones.append(
            Zone(
                name=str(item.get("name", f"zone_{index}")),
                path=str(item["path"]),
                forbidden_imports=_str_tuple(
                    item.get("forbidden_imports"), warnings, f"zones[{index}].forbidden_imports"),
                reason=str(item["reason"]) if item.get("reason") else None,
            )
        )
    return tuple(zones)
