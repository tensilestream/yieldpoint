"""Saying "yes, I meant that" — in the source, with a reason.

Every rule here will sometimes be right about the code and wrong about the
intent. Changing what a test asserts *is* a change in what is verified, and
Yieldpoint is correct to say so; sometimes it was the point. Without a way to
record that, the finding is permanent noise, and a verifier that cannot be
answered gets switched off wholesale rather than tuned. The escape hatch is
what keeps the rest of the rules switched on.

    # yieldpoint: allow assertion_monotonicity - broadened to cover YAML clients
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
reported by ``yieldpoint stats``. A growing count is a signal about the rule or
the team, and burying it is how this kind of mechanism rots.

Scope is the line the finding points at, or the two lines above it, so the
comment sits where a reader will see it next to what it excuses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

#: ``# yieldpoint: allow <rule> [until YYYY-MM-DD] [owner=<who>] - <reason>``.
#: An em dash, a hyphen or a colon all separate; people type whichever their
#: editor gives them.
#:
#: ``until`` and ``owner`` sit before the separator, so a reason is free to
#: contain either word. ``until`` matches only a date-shaped token, so "allow
#: x - keep until the rewrite" is still just a reason.
PATTERN = re.compile(
    r"#\s*yieldpoint\s*:\s*allow\s+(?P<rule>[a-z_]+)"
    r"(?:\s+until\s+(?P<until>\d{4}-\d{2}-\d{2}))?"
    r"(?:\s+owner\s*=\s*(?P<owner>[^\s-]+))?"
    r"\s*[-—:]\s*(?P<reason>\S.*)$",
    re.IGNORECASE,
)

#: How far above the finding the comment may sit.
LOOKBACK = 2


@dataclass(frozen=True)
class Acknowledgement:
    rule: str
    reason: str
    line: int

    until: str = ""
    """The date the author said this should stop being acceptable, as written.

    Stored, never judged here. Deciding whether it has passed needs the current
    date, and a rule that reads a clock makes the same commit pass today and
    fail tomorrow (RULES.md section 4). An acknowledgement therefore keeps
    suppressing whatever its expiry says; only a command that says out loud
    that it is reading the clock may act on it."""

    owner: str = ""
    """Who this debt belongs to. Not whoever tripped over it last."""


def _comment_lines(source: str) -> frozenset[int] | None:
    """Lines holding a real Python comment, or ``None`` if that cannot be told.

    Without this, an acknowledgement written *about* acknowledgements — in a
    docstring, a README example, a test fixture string — suppresses findings on
    the lines beneath it. This module's own docstring did exactly that: the
    example on line 10 silenced any monotonicity finding on lines 10 to 12.

    ``None`` rather than an empty set when the source will not tokenize, so a
    file this cannot read keeps the old behaviour instead of silently losing
    every acknowledgement in it.
    """
    import io
    import tokenize

    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (SyntaxError, tokenize.TokenError, IndentationError, ValueError):
        return None
    return frozenset(token.start[0] for token in tokens
                     if token.type == tokenize.COMMENT)


def scan(source: str) -> dict[int, list[Acknowledgement]]:
    """Every acknowledgement in ``source``, keyed by the line it appears on."""
    real = _comment_lines(source)
    found: dict[int, list[Acknowledgement]] = {}
    for index, text in enumerate(source.splitlines(), start=1):
        match = PATTERN.search(text)
        if match is None or (real is not None and index not in real):
            continue
        found.setdefault(index, []).append(
            Acknowledgement(
                rule=match.group("rule").strip().lower(),
                reason=match.group("reason").strip(),
                line=index,
                until=(match.group("until") or "").strip(),
                owner=(match.group("owner") or "").strip(),
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
        if not covers(marks, finding.rule, finding.line):
            kept.append(finding)
        elif getattr(finding, "inherited", False):
            # Acknowledged, and this change made it worse anyway.
            kept.append(_still_growing(finding))
        else:
            acknowledged.append(finding)
    return kept, acknowledged


#: What an acknowledgement is answering, and what it is not.
STILL_GROWING = (
    "This is acknowledged, and this change added to it anyway. An "
    "acknowledgement answers the debt as it stood, not unlimited growth — "
    "keep this change from adding to it, or rewrite the acknowledgement to say "
    "the new size is the one you mean."
)


def _still_growing(finding):
    """An acknowledged finding the change worsened, reported rather than muted.

    Without this an acknowledgement is a permanent off switch: a file allowed
    at four hundred lines could reach nine hundred in silence, which is how the
    mechanism becomes decorative. Reported, never blocking — the point is that
    the growth is visible, not that it is refused.
    """
    return replace(finding, prescription=STILL_GROWING)


__all__ = ["Acknowledgement", "scan", "covers", "apply", "PATTERN", "LOOKBACK"]
