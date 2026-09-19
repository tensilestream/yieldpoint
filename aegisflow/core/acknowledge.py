"""Saying "yes, I meant that" — in the source, with a reason.

Every rule here will sometimes be right about the code and wrong about the
intent. Changing what a test asserts *is* a change in what is verified, and
AegisFlow is correct to say so; sometimes it was the point. Without a way to
record that, the finding is permanent noise, and a verifier that cannot be
answered gets switched off wholesale rather than tuned. The escape hatch is
what keeps the rest of the rules switched on.

    # aegisflow: allow assertion_monotonicity - broadened to cover YAML clients
    def test_every_client_resolves_a_path(self):
        ...

Three deliberate constraints, because a suppression mechanism that is too easy
becomes an off switch:

**It names one rule.** There is no blanket form. Acknowledging a monotonicity
finding does not also silence a dangling reference on the same line.

**It requires a reason.** A comment with no text after the separator does not
suppress anything. The reason is for the human reading the diff, who otherwise
cannot tell a considered decision from a nuisance dismissal.

**It stays visible.** Acknowledged findings are counted on the verdict and
reported by ``aegisflow stats``. A growing count is a signal about the rule or
the team, and burying it is how this kind of mechanism rots.

Scope is the line the finding points at, or the two lines above it, so the
comment sits where a reader will see it next to what it excuses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: ``# aegisflow: allow <rule> - <reason>``. An em dash, a hyphen or a colon all
#: separate; people type whichever their editor gives them.
PATTERN = re.compile(
    r"#\s*aegisflow\s*:\s*allow\s+(?P<rule>[a-z_]+)\s*[-—:]\s*(?P<reason>\S.*)$",
    re.IGNORECASE,
)

#: How far above the finding the comment may sit.
LOOKBACK = 2


@dataclass(frozen=True)
class Acknowledgement:
    rule: str
    reason: str
    line: int


def scan(source: str) -> dict[int, list[Acknowledgement]]:
    """Every acknowledgement in ``source``, keyed by the line it appears on."""
    found: dict[int, list[Acknowledgement]] = {}
    for index, text in enumerate(source.splitlines(), start=1):
        match = PATTERN.search(text)
        if match is None:
            continue
        found.setdefault(index, []).append(
            Acknowledgement(
                rule=match.group("rule").strip().lower(),
                reason=match.group("reason").strip(),
                line=index,
            )
        )
    return found


def covers(marks: dict[int, list[Acknowledgement]], rule: str, line: int) -> bool:
    """Whether an acknowledgement applies to ``rule`` at ``line``."""
    for candidate in range(max(1, line - LOOKBACK), line + 1):
        for mark in marks.get(candidate, ()):
            if mark.rule == rule.lower():
                return True
    return False


def apply(findings, source: str | None):
    """Split findings into those still reported and those acknowledged.

    Returns ``(kept, acknowledged)``. An empty source acknowledges nothing, so a
    file that could not be read never silences a rule by accident.
    """
    if not source or not findings:
        return list(findings), []
    marks = scan(source)
    if not marks:
        return list(findings), []

    kept, acknowledged = [], []
    for finding in findings:
        if covers(marks, finding.rule, finding.line):
            acknowledged.append(finding)
        else:
            kept.append(finding)
    return kept, acknowledged


__all__ = ["Acknowledgement", "scan", "covers", "apply", "PATTERN", "LOOKBACK"]
