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

CONFIG_FILENAME = ".yieldpoint.json"

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


DEFAULT_IGNORE = (
    "**/node_modules/**", "**/.git/**", "**/dist/**", "**/build/**",
    "**/.venv/**", "**/venv/**", "**/__pycache__/**", "**/.tox/**",
    "**/target/**", "**/.mypy_cache/**", "**/.ruff_cache/**",
    "**/site-packages/**", "**/.eggs/**", "**/*.egg-info/**",
)


@dataclass(frozen=True)
class Scan:
    """What a whole-repository audit looks at."""

    ignore: tuple[str, ...] = DEFAULT_IGNORE
    max_file_bytes: int = 1_000_000


@dataclass(frozen=True)
class CustomRule:
    """A project-defined rule, declared in configuration rather than in code.

    Declarative on purpose: `.yieldpoint.json` is repo-committed, so a rule that
    could name code to run would mean cloning a repository executes it. New rule
    *kinds* come from installed packages, which is an explicit act; new rule
    *instances* come from config, which is not.
    """

    name: str
    severity: Status | None = Status.REPAIR
    path: str = ""
    forbid_call: str = ""
    forbid_import: str = ""
    require_name_pattern: str = ""
    message: str = ""


@dataclass(frozen=True)
class Structure:
    """Maintainability limits.

    Differential by default: a violation is reported only when this change
    introduced or worsened it, so the rules can be switched on in an existing
    repository without blaming inherited debt. ``greenfield`` makes them
    absolute, which is what a project starting clean wants.
    """

    severity: Status | None = Status.REPAIR
    greenfield: bool = False
    max_file_lines: int = 300
    max_lines: int = 50
    max_parameters: int = 5
    max_nesting: int = 4
    max_complexity: int = 10
    max_added_lines: int = 400
    max_change_lines: int = 1200
    forbid_utility_modules: bool = True
    duplicate_implementation: Status | None = Status.REPAIR
    custom: tuple[CustomRule, ...] = ()


@dataclass(frozen=True)
class ContinuousIntegration:
    """Integrity of the checks themselves.

    An agent blocked from weakening an assertion can still weaken the build that
    runs it. Analysis is lexical — CI definitions are YAML and the core takes no
    dependencies — so these findings warn and cannot block.
    """

    check_removed: Status | None = Status.REPAIR
    check_disabled: Status | None = Status.REPAIR
    paths: tuple[str, ...] = (
        "**/.github/workflows/*.yml", "**/.github/workflows/*.yaml",
        ".github/workflows/*.yml", ".github/workflows/*.yaml",
        "**/.pre-commit-config.yaml", ".pre-commit-config.yaml",
        "**/.gitlab-ci.yml", ".gitlab-ci.yml",
    )


@dataclass(frozen=True)
class Refactor:
    """Rules for changes that restructure code rather than change behaviour.

    Applies to every Python file, not only protected tests — a refactor that
    leaves a call site pointing at a renamed definition still parses, and fails
    only when that path runs.
    """

    dangling_reference: Status | None = Status.REPAIR
    export_removed: Status | None = Status.REPAIR


@dataclass(frozen=True)
class Subjects:
    """How subject expressions are matched across a change."""

    accessor_equivalence: bool = True
    """Treat ``x.total`` and ``x.getTotal()`` as one subject. Applied only after
    exact matching fails, so it can suppress a false finding, never create one."""


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
    """Semantic no-progress detection: an agent going round without moving."""

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
class Routing:
    """Thresholds for the risk score and the model tier it implies.

    Configurable because the right answer is a property of the codebase, not of
    this package. Twelve changed lines is cosmetic in a service and a
    substantial edit in a compiler; a team that cannot move that number without
    forking will instead stop using the routing, which costs them the whole
    benefit to avoid a disagreement about one constant.

    ``escalate_paths`` raises anything matching straight to ``critical``,
    whatever its size — the escape hatch for code whose importance is not
    visible in its shape (a payments calculation, a migration, a security
    boundary). This is how an organisation encodes what it knows and the
    syntax tree does not.
    """

    small_churn: int = 12
    moderate_churn: int = 60
    large_churn: int = 250
    max_complexity: int = 12

    critical_importance: float = 0.9
    """Blast-radius percentile above which a change is treated as high risk.

    A percentile, so the default holds whatever the repository's size: 0.9
    means the most-depended-upon tenth of modules, which is roughly where
    "everything breaks if this is wrong" begins in practice."""

    use_import_graph: bool = True
    """Compute importance from the import graph. Off makes the blast-radius
    rules dormant rather than wrong — they stay ``None`` and never fire."""

    escalate_paths: tuple[str, ...] = ()
    tiers: dict[str, str] = field(default_factory=dict)
    """Tier name to the caller's model name. Empty means the caller maps it."""

    enabled: bool = True


@dataclass(frozen=True)
class Metrics:
    """Local accounting of what Yieldpoint did.

    On by default because a value claim nobody can check is worth nothing, and
    this one costs a line of JSON per verdict. Nothing leaves the machine: there
    is no network call anywhere in this package. Set ``enabled`` false, or export
    ``YIELDPOINT_NO_METRICS``, to switch it off.
    """

    enabled: bool = True
    path: str = ".yieldpoint/metrics.jsonl"

    price_per_million: float = 0.0
    """Your input-token price, per million, for the cost estimate.

    Zero means no cost is shown. There is no default rate on purpose: prices
    differ by vendor, by model and by month, and a figure baked in here would
    be stale and unreproducible — which RULES.md section 5 forbids. State your
    own and the report states it back beside the result. Unlike ``sink`` this
    is safe in a committed file: it is a number, and a number cannot execute."""

    #: Where events are exported is deliberately **not** here. This file is
    #: committed, and SECURITY.md states that configuration must never be able
    #: to name an executable: a repository that could would run a command on
    #: every machine that cloned it. The sink is read from the environment
    #: instead — see ``yieldpoint/sink.py``.

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
    def load(cls, source: "str | Path | dict[str, Any] | Policy | None" = None) -> "Policy":
        """Load from a path, a parsed dict, an existing policy, or the defaults.

        ``None`` searches upward from the working directory for
        ``.yieldpoint.json`` and falls back to built-in defaults.
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
