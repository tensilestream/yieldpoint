"""Policy loading and normalisation.

Reads ``.aegisflow.json`` into typed, immutable rules. A rule's configured value
is the :class:`Status` it returns when violated, or ``"off"`` to disable it — so
severity is policy, not code, and a team can start every rule at ``repair`` and
tighten later once a false-positive rate is known (RULES.md section 6).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
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
class GeneratedCode:
    """How to treat files that a tool produced rather than a person.

    ``on_hand_edit`` fires only when an agent is editing such a file *by hand*.
    Regenerating one and committing the result is normal, so the diff path stays
    silent; the hook path, which sees an edit being composed, does not.
    """

    detect: bool = True
    on_hand_edit: Status | None = Status.REPAIR
    extra_patterns: tuple[str, ...] = ()


@dataclass(frozen=True)
class Voice:
    """Overrides applied when the user cannot see the change.

    A ``repair`` finding is reasonable on a screen: the agent fixes it and the
    human sees the diff either way. Spoken, nobody sees anything, so the default
    raises findings to ``escalate`` — severity is a function of modality, not
    only of what went wrong.
    """

    severity_floor: Status | None = Status.ESCALATE
    max_spoken_findings: int = 3
    confirm_on_removals: int = 2


@dataclass(frozen=True)
class Policy:
    version: str = "1.0"
    project_name: str = "unnamed"
    languages: tuple[str, ...] = ("python",)
    test_contract: TestContract = field(default_factory=TestContract)
    boundaries: Boundaries = field(default_factory=Boundaries)
    loop_breaker: LoopBreaker = field(default_factory=LoopBreaker)
    linters: Linters = field(default_factory=Linters)
    voice: Voice = field(default_factory=Voice)
    generated: GeneratedCode = field(default_factory=GeneratedCode)
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
        from .policyreader import read

        return read(raw, source_name=source_name)

    def for_voice(self) -> "Policy":
        """This policy with every rule raised to the voice severity floor.

        Returns ``self`` when no floor is configured, so voice mode is opt-out
        without special-casing at the call site.
        """
        floor = self.voice.severity_floor
        if floor is None:
            return self

        def raise_to(status: Status | None) -> Status | None:
            if status is None:
                return None
            return status if status.severity >= floor.severity else floor

        contract = self.test_contract
        return replace(
            self,
            test_contract=replace(
                contract,
                assertion_monotonicity=raise_to(contract.assertion_monotonicity),
                forbid_vacuous_assertions=raise_to(contract.forbid_vacuous_assertions),
                forbid_new_skip_markers=raise_to(contract.forbid_new_skip_markers),
                forbid_swallowed_exceptions=raise_to(contract.forbid_swallowed_exceptions),
            ),
            boundaries=replace(self.boundaries, on_violation=raise_to(self.boundaries.on_violation)),
        )

    def protects(self, path: str) -> bool:
        from . import glob

        return glob.matches_any(self.test_contract.protected_patterns, path)
