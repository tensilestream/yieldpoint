"""Reading one configuration value, or one section, safely.

Split from policyreader.py because the two change for different reasons: that
file grows when the policy gains a section, this one when a value needs a new
kind of validation.

Everything here takes the same shape — a raw value, a default, and the list of
warnings to append to. A bad value never raises and never silently becomes
something else: the default applies and the reason is recorded, so a
misconfiguration is visible at the point of use rather than discovered from
behaviour months later.
"""

from __future__ import annotations

from typing import Any

from .policy import (
    CustomRule,
    Linters,
    Routing,
    Status,
    Structure,
    Zone,
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


def _routing(raw: dict[str, Any], warnings: list[str]) -> Routing:
    """Read the routing thresholds, keeping the ordering they must satisfy.

    A configuration whose thresholds cross would silently make a level
    unreachable, so it is rejected with a warning and the defaults stand.
    """
    defaults = Routing()
    small = _positive(raw.get("small_churn"), defaults.small_churn, warnings, "small_churn")
    moderate = _positive(
        raw.get("moderate_churn"), defaults.moderate_churn, warnings, "moderate_churn")
    large = _positive(raw.get("large_churn"), defaults.large_churn, warnings, "large_churn")

    if not small < moderate < large:
        warnings.append(
            f"routing: thresholds must increase (small {small} < moderate {moderate} "
            f"< large {large}); using the defaults"
        )
        small, moderate, large = (
            defaults.small_churn, defaults.moderate_churn, defaults.large_churn)

    tiers = raw.get("tiers")
    return Routing(
        small_churn=small,
        moderate_churn=moderate,
        large_churn=large,
        max_complexity=_positive(
            raw.get("max_complexity"), defaults.max_complexity, warnings, "max_complexity"),
        critical_importance=_fraction(
            raw.get("critical_importance"), defaults.critical_importance,
            warnings, "critical_importance"),
        use_import_graph=bool(raw.get("use_import_graph", True)),
        escalate_paths=_str_tuple(raw.get("escalate_paths"), warnings, "routing.escalate_paths"),
        tiers=dict(tiers) if isinstance(tiers, dict) else {},
        enabled=bool(raw.get("enabled", True)),
    )


def _fraction(value: Any, fallback: float, warnings: list[str], name: str) -> float:
    if value is None:
        return fallback
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
        warnings.append(f"routing.{name}: expected a number between 0 and 1, got {value!r}")
        return fallback
    return float(value)


def _positive(value: Any, fallback: int, warnings: list[str], name: str) -> int:
    if value is None:
        return fallback
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        warnings.append(f"routing.{name}: expected a positive integer, got {value!r}")
        return fallback
    return value


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


def _structure(raw: dict[str, Any], warnings: list[str]) -> Structure:
    defaults = Structure()
    numbers = {
        field: _int(raw.get(field), getattr(defaults, field), warnings, f"structure.{field}")
        for field in (
            "max_file_lines", "max_lines", "max_parameters", "max_nesting",
            "max_complexity", "max_added_lines", "max_change_lines",
        )
    }
    return Structure(
        severity=_status(raw.get("severity"), Status.REPAIR, warnings, "structure.severity"),
        greenfield=bool(raw.get("greenfield", False)),
        gates=bool(raw.get("gates", False)),
        forbid_utility_modules=bool(raw.get("forbid_utility_modules", True)),
        duplicate_implementation=_status(
            raw.get("duplicate_implementation"), Status.REPAIR, warnings,
            "structure.duplicate_implementation"),
        custom=_custom_rules(raw.get("custom"), warnings),
        **numbers,
    )


def _custom_rules(value: Any, warnings: list[str]) -> tuple[CustomRule, ...]:
    if not isinstance(value, list):
        if value is not None:
            warnings.append("structure.custom: expected a list; ignoring.")
        return ()
    rules: list[CustomRule] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict) or not item.get("name"):
            warnings.append(f"structure.custom[{index}]: missing 'name'; ignoring.")
            continue
        rules.append(CustomRule(
            name=str(item["name"]),
            severity=_status(
                item.get("severity"), Status.REPAIR, warnings,
                f"structure.custom[{index}].severity"),
            path=str(item.get("path", "")),
            forbid_call=str(item.get("forbid_call", "")),
            forbid_import=str(item.get("forbid_import", "")),
            require_name_pattern=str(item.get("require_name_pattern", "")),
            message=str(item.get("message", "")),
        ))
    return tuple(rules)


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
