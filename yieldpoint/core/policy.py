"""Policy loading and normalisation.

Reads ``.yieldpoint.json`` into typed, immutable rules. A rule's configured value
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

from .policysections import (  # noqa: F401
    CONFIG_FILENAME, DEFAULT_IGNORE, DEFAULT_PROTECTED_PATTERNS,
    Boundaries, ContinuousIntegration, CustomRule, GeneratedCode,
    Linters, LoopBreaker, Metrics, Refactor, Routing, Scan, Structure,
    Subjects, TestContract, Voice, Zone,
)


@dataclass(frozen=True)
class Policy:
    version: str = "1.0"
    project_name: str = "unnamed"
    languages: tuple[str, ...] = ("python",)
    test_contract: TestContract = field(default_factory=TestContract)
    subjects: Subjects = field(default_factory=Subjects)
    refactor: Refactor = field(default_factory=Refactor)
    ci: ContinuousIntegration = field(default_factory=ContinuousIntegration)
    structure: Structure = field(default_factory=Structure)
    scan: Scan = field(default_factory=Scan)
    boundaries: Boundaries = field(default_factory=Boundaries)
    loop_breaker: LoopBreaker = field(default_factory=LoopBreaker)
    linters: Linters = field(default_factory=Linters)
    voice: Voice = field(default_factory=Voice)
    generated: GeneratedCode = field(default_factory=GeneratedCode)
    metrics: Metrics = field(default_factory=Metrics)
    routing: Routing = field(default_factory=Routing)
    source: str = "defaults"
    warnings: tuple[str, ...] = ()

    # ---------------------------------------------------------------- loading

    @classmethod
    def load(cls, source: "str | Path | dict[str, Any] | Policy | None" = None,
             *, root: str | Path | None = None) -> "Policy":
        """Load from a path, a parsed dict, an existing policy, or the defaults.

        ``None`` searches upward from the working directory for
        ``.yieldpoint.json`` and falls back to built-in defaults.
        """
        if isinstance(source, Policy):
            return source
        if isinstance(source, dict):
            return cls.from_dict(source, source_name="<dict>")
        if source is None:
            found = cls.discover(Path(root) if root is not None else Path.cwd())
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
