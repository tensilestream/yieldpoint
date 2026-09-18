"""Policy loading and normalisation.

Reads ``.aegisflow.json`` into typed, immutable rules. A rule's configured value
is the :class:`Status` it returns when violated, or ``"off"`` to disable it — so
severity is policy, not code, and a team can start every rule at ``repair`` and
tighten later once a false-positive rate is known (RULES.md section 6).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .verdict import Status

CONFIG_FILENAME = ".aegisflow.json"

DEFAULT_PROTECTED_PATTERNS = (
    "**/tests/**",
    "**/test/**",
    "**/*_test.py",
    "**/test_*.py",
    "**/*.test.*",
    "**/*.spec.*",
    "**/fixtures/**",
)


@dataclass(frozen=True)
class TestContract:
    """Rules governing edits to protected test files."""

    protected_patterns: tuple[str, ...] = DEFAULT_PROTECTED_PATTERNS
    assertion_monotonicity: Status | None = Status.REPAIR
    forbid_vacuous_assertions: Status | None = Status.REPAIR
    forbid_new_skip_markers: Status | None = Status.REPAIR
    forbid_swallowed_exceptions: Status | None = Status.REPAIR


@dataclass(frozen=True)
class Zone:
    """One architectural boundary: what ``path`` may not import."""

    name: str
    path: str
    forbidden_imports: tuple[str, ...] = ()
    reason: str | None = None


@dataclass(frozen=True)
class Boundaries:
    on_violation: Status | None = Status.REPAIR
    zones: tuple[Zone, ...] = ()


@dataclass(frozen=True)
class LoopBreaker:
    """Semantic no-progress detection; see PLAN_AND_POSITIONING.md section 4.3."""

    window: int = 6
    max_repeats_without_progress: int = 3
    on_trip: Status | None = Status.ESCALATE


@dataclass(frozen=True)
class Linters:
    """Optional integration with the project's existing linters and formatters.

    Off by default, deliberately. Enabling it makes verdicts depend on which tool
    versions are installed, which is an environment read the core otherwise
    forbids — so linter findings carry ``Confidence.EXTERNAL`` and can advise but
    never block.
    """

    enabled: bool = False
    severity: Status | None = Status.REPAIR
    timeout_seconds: int = 10
    include_slow: bool = False
    tools: tuple[str, ...] = ()


@dataclass(frozen=True)
class Policy:
    version: str = "1.0"
    project_name: str = "unnamed"
    languages: tuple[str, ...] = ("python",)
    test_contract: TestContract = field(default_factory=TestContract)
    boundaries: Boundaries = field(default_factory=Boundaries)
    loop_breaker: LoopBreaker = field(default_factory=LoopBreaker)
    linters: Linters = field(default_factory=Linters)
    source: str = "defaults"
    warnings: tuple[str, ...] = ()

    # ---------------------------------------------------------------- loading

    @classmethod
    def load(cls, source: "str | Path | dict[str, Any] | Policy | None" = None) -> "Policy":
        """Load from a path, a parsed dict, an existing policy, or the defaults.

        ``None`` searches upward from the working directory for
        ``.aegisflow.json`` and falls back to built-in defaults.
        """
        if isinstance(source, Policy):
            return source
        if isinstance(source, dict):
            return cls.from_dict(source, source_name="<dict>")
        if source is None:
            found = cls.discover(Path.cwd())
            if found is None:
                return cls()
            source = found
        path = Path(source)
        if path.is_dir():
            path = path / CONFIG_FILENAME
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise FileNotFoundError(f"no policy file at {path}") from None
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path} is not valid JSON: {exc}") from None
        return cls.from_dict(raw, source_name=str(path))

    @staticmethod
    def discover(start: Path) -> Path | None:
        """Walk upward for a config file. Returns ``None`` rather than guessing."""
        current = start.resolve()
        for directory in (current, *current.parents):
            candidate = directory / CONFIG_FILENAME
            if candidate.is_file():
                return candidate
        return None

    @classmethod
    def from_dict(cls, raw: dict[str, Any], *, source_name: str = "<dict>") -> "Policy":
        warnings: list[str] = []
        project = _section(raw, "project", warnings)
        contract = _section(raw, "test_contract", warnings)
        boundaries = _section(raw, "boundaries", warnings)
        breaker = _section(raw, "loop_breaker", warnings)
        linters = _section(raw, "linters", warnings)

        patterns = _str_tuple(contract.get("protected_patterns"), warnings, "protected_patterns")

        return cls(
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
                on_trip=_status(
                    breaker.get("on_trip"), Status.ESCALATE, warnings, "on_trip"),
            ),
            linters=_linters(linters, warnings),
            source=source_name,
            warnings=tuple(warnings),
        )

    def protects(self, path: str) -> bool:
        from . import glob

        return glob.matches_any(self.test_contract.protected_patterns, path)


# -------------------------------------------------------------------- helpers


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
