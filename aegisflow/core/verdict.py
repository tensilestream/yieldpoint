"""The verdict contract.

This module defines the product's public interface. Every other surface — the
LangGraph node, the CLI, a future MCP server or container — is a translation
layer over :class:`Verdict`, and the JSON form produced by :meth:`Verdict.to_dict`
is the cross-language API. Treat its shape as versioned and breaking to change.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Iterable, Sequence

#: Incremented on any breaking change to the serialised verdict shape.
SCHEMA_VERSION = 1


class Status(str, Enum):
    """What a finding demands of the caller, ordered by severity.

    The graph routes on this value, so the set is deliberately small and its
    meaning is about *action*, not about how bad something feels.
    """

    PASS = "pass"
    """Nothing to do. Apply the change."""

    REPAIR = "repair"
    """The agent can fix this itself; route back to generation with the prescription."""

    ESCALATE = "escalate"
    """A human must look. The agent is unlikely to resolve it by retrying."""

    BLOCK = "block"
    """Do not apply, and do not retry. Reserved for rules with a measured
    false-positive rate; see RULES.md section 6."""

    @property
    def severity(self) -> int:
        return _SEVERITY[self]

    @classmethod
    def worst(cls, statuses: Iterable["Status"]) -> "Status":
        """Merge statuses by taking the most severe. Empty input means PASS."""
        return max(statuses, key=lambda s: s.severity, default=cls.PASS)


_SEVERITY = {Status.PASS: 0, Status.REPAIR: 1, Status.ESCALATE: 2, Status.BLOCK: 3}


class Confidence(str, Enum):
    """How the finding was derived.

    Surfaced to the caller because it changes what the finding is worth: an
    ``EXACT`` finding came from a real parse of both sides, a ``LEXICAL`` one from
    pattern matching and may be wrong. Never let a LEXICAL finding block.
    """

    EXACT = "exact"
    LEXICAL = "lexical"


@dataclass(frozen=True)
class Finding:
    """One rule violation at one location.

    Frozen so a verdict cannot be mutated after it is returned, and ordered by a
    stable key so output is byte-identical across runs (RULES.md section 4).
    """

    rule: str
    status: Status
    file: str
    line: int
    detail: str
    prescription: str
    before: str | None = None
    after: str | None = None
    symbol: str | None = None
    confidence: Confidence = Confidence.EXACT

    def __post_init__(self) -> None:
        if self.line < 0:
            raise ValueError(f"line must be non-negative, got {self.line}")
        if not self.rule:
            raise ValueError("finding requires a rule name")
        if self.status is Status.BLOCK and self.confidence is Confidence.LEXICAL:
            raise ValueError(
                f"rule {self.rule!r} cannot BLOCK on a lexical finding; "
                "see RULES.md section 6"
            )

    @property
    def sort_key(self) -> tuple[str, int, str, str]:
        return (self.file, self.line, self.rule, self.detail)

    @property
    def location(self) -> str:
        return f"{self.file}:{self.line}"

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "rule": self.rule,
            "status": self.status.value,
            "file": self.file,
            "line": self.line,
            "detail": self.detail,
            "prescription": self.prescription,
            "confidence": self.confidence.value,
        }
        for key in ("before", "after", "symbol"):
            value = getattr(self, key)
            if value is not None:
                out[key] = value
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Finding":
        return cls(
            rule=data["rule"],
            status=Status(data["status"]),
            file=data["file"],
            line=int(data["line"]),
            detail=data["detail"],
            prescription=data["prescription"],
            before=data.get("before"),
            after=data.get("after"),
            symbol=data.get("symbol"),
            confidence=Confidence(data.get("confidence", Confidence.EXACT.value)),
        )


@dataclass(frozen=True)
class Verdict:
    """The result of verifying one change set.

    Construct with :meth:`of` rather than directly, so that status derivation and
    finding ordering stay in one place.
    """

    status: Status = Status.PASS
    findings: tuple[Finding, ...] = field(default_factory=tuple)
    checked: tuple[str, ...] = field(default_factory=tuple)
    skipped: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def of(
        cls,
        findings: Sequence[Finding] = (),
        *,
        checked: Sequence[str] = (),
        skipped: Sequence[str] = (),
    ) -> "Verdict":
        """Build a verdict, deriving status from the most severe finding.

        ``checked`` and ``skipped`` record which files were actually analysed and
        which were not, so no caller can mistake "nothing ran" for "nothing wrong"
        (RULES.md section 5).
        """
        ordered = tuple(sorted(findings, key=lambda f: f.sort_key))
        return cls(
            status=Status.worst(f.status for f in ordered),
            findings=ordered,
            checked=tuple(sorted(checked)),
            skipped=tuple(sorted(skipped)),
        )

    def __bool__(self) -> bool:
        """True when the change may be applied as-is."""
        return self.status is Status.PASS

    def for_rule(self, rule: str) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.rule == rule)

    def merge(self, other: "Verdict") -> "Verdict":
        return Verdict.of(
            self.findings + other.findings,
            checked=self.checked + other.checked,
            skipped=self.skipped + other.skipped,
        )

    def demote(self, ceiling: Status) -> "Verdict":
        """Cap every finding at ``ceiling``.

        Used when a rule set has no measured false-positive rate yet and is
        therefore not permitted to block.
        """
        if not self.findings:
            return self
        capped = tuple(
            replace(f, status=f.status if f.status.severity <= ceiling.severity else ceiling)
            for f in self.findings
        )
        return Verdict.of(capped, checked=self.checked, skipped=self.skipped)

    @property
    def prescription(self) -> str:
        """The whole remediation, formatted for an agent to consume."""
        if not self.findings:
            return ""
        lines = []
        for finding in self.findings:
            lines.append(f"{finding.location}  [{finding.rule}] {finding.detail}")
            lines.append(f"    -> {finding.prescription}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": self.status.value,
            "findings": [f.to_dict() for f in self.findings],
            "checked": list(self.checked),
            "skipped": list(self.skipped),
        }

    def to_json(self, *, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Verdict":
        version = data.get("schema_version")
        if version != SCHEMA_VERSION:
            raise ValueError(
                f"unsupported verdict schema_version {version!r}; "
                f"this build reads {SCHEMA_VERSION}"
            )
        return cls.of(
            [Finding.from_dict(f) for f in data.get("findings", [])],
            checked=data.get("checked", ()),
            skipped=data.get("skipped", ()),
        )
