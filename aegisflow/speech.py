"""Rendering a verdict for a listener, and confirming a change by voice.

Voice is the modality where this project is load-bearing: there is no diff on a
screen, so nothing reviews the change unless the verifier does.

Two problems shape this module, and neither is text-to-speech.

**A verdict must survive being heard.** `tests/test_invoice.py:41` read aloud is
noise. Speech gets names, not paths, and one sentence before any detail.

**A confirmation must survive being misheard.** Asking "shall I proceed?" and
listening for "yes" is unsafe: speech recognition mistakes short words, and
background conversation contains them. So a risky change asks for a specific
uncommon word, derived deterministically from the change itself — the same change
always asks for the same word, and no other change asks for that one.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .core.verdict import Status, Verdict

#: Phonetically distinct words. Chosen so a listener cannot confuse two of them,
#: and so none is a word that occurs naturally in conversation about code.
_WORDS = (
    "anchor", "beacon", "cobalt", "dynamo", "ember", "falcon", "granite", "harbor",
    "indigo", "jasper", "kestrel", "lantern", "meadow", "nutmeg", "obsidian", "pelican",
    "quartz", "ripple", "saffron", "tundra", "umbra", "velvet", "walnut", "xenon",
    "yonder", "zephyr", "amber", "bramble", "cinder", "driftwood", "eclipse", "fathom",
)

#: Summary-level phrasing. Deliberately covers every kind a rule can report:
#: assertion_monotonicity fires on removal *and* downgrade, so a phrase naming
#: only one of them would be wrong half the time.
_RULE_PHRASES = {
    "assertion_monotonicity": "the tests now verify less than before",
    "vacuous_assertion": "a test asserts something that is always true",
    "disabled_assertion": "an assertion can no longer fail",
    "skip_marker": "a test was skipped",
    "empty_test": "a test has no assertions",
}

#: Detail-level substitutions. Relation names and arrows are unreadable aloud.
_SPOKEN = (
    (" -> ", " to "),
    ("non_null", "not null"),
    ("eq", "equality"),
    ("membership", "membership"),
    ("truthy", "truthiness"),
    ("vacuous", "always true"),
    ("_", " "),
)

_FILLER = re.compile(r"\b(?:um|uh|er|like|okay|ok|so|please|yes|yeah|now|just)\b")
_NOISE = re.compile(r"[^a-z\s]")


@dataclass(frozen=True)
class Confirmation:
    """A spoken checkpoint the user must clear before a risky change is applied."""

    token: str
    question: str
    reasons: tuple[str, ...] = ()

    def matches(self, spoken: str) -> bool:
        """Did the listener actually say the word?

        Tolerant of transcription noise — casing, punctuation, filler words — and
        intolerant of everything else. Assent is never inferred from "yes".
        """
        cleaned = _NOISE.sub(" ", (spoken or "").lower())
        words = set(_FILLER.sub(" ", cleaned).split())
        return self.token in words


@dataclass(frozen=True)
class Utterance:
    """What to say, in the order it should be said."""

    summary: str
    details: tuple[str, ...] = ()
    confirmation: Confirmation | None = None

    @property
    def requires_assent(self) -> bool:
        return self.confirmation is not None

    def full(self) -> str:
        parts = [self.summary, *self.details]
        if self.confirmation:
            parts.append(self.confirmation.question)
        return " ".join(parts)


def speak(
    verdict: Verdict,
    *,
    deletions: tuple[str, ...] = (),
    max_details: int = 3,
    confirm_threshold: int = 2,
) -> Utterance:
    """Render ``verdict`` as speech.

    ``deletions`` names files the change would remove — a listener cannot see
    that happen, so it is always worth saying and always worth confirming.
    """
    summary = _summary(verdict, deletions)
    details = _details(verdict, max_details)
    confirmation = _confirmation(verdict, deletions, confirm_threshold)
    return Utterance(summary=summary, details=details, confirmation=confirmation)


def _summary(verdict: Verdict, deletions: tuple[str, ...]) -> str:
    checked = len(verdict.checked)
    scope = "No files were checked." if not checked else (
        f"{_count(checked, 'file')} checked."
    )

    if verdict.skipped and not verdict.findings:
        return f"{scope} {_count(len(verdict.skipped), 'file')} could not be verified."

    if verdict.status is Status.PASS:
        tail = "Assertions held."
        if deletions:
            tail = f"Assertions held, but {_count(len(deletions), 'file')} would be deleted."
        return f"{scope} {tail}"

    rules = {f.rule for f in verdict.findings}
    lead = _RULE_PHRASES.get(
        sorted(rules)[0], sorted(rules)[0].replace("_", " ").replace("lint.", "")
    )
    return (
        f"{scope} {_count(len(verdict.findings), 'problem')}: "
        f"{lead}{'.' if len(rules) == 1 else ', among others.'}"
    )


def _details(verdict: Verdict, limit: int) -> tuple[str, ...]:
    """Say what specifically is wrong.

    Each finding's own detail is spoken rather than its rule's phrase, because
    two findings from one rule are usually about different subjects, and hearing
    the same sentence twice tells the listener nothing.
    """
    spoken = []
    for finding in verdict.findings[:limit]:
        where = finding.symbol or _spoken_path(finding.file)
        spoken.append(f"In {where}, {_readable(finding.detail)}")
    remaining = len(verdict.findings) - len(spoken)
    if remaining > 0:
        spoken.append(f"And {_count(remaining, 'more problem')}.")
    return tuple(spoken)


def _readable(detail: str) -> str:
    """Strip notation that only works on a screen."""
    text = detail[0].lower() + detail[1:] if detail else detail
    for pattern, replacement in _SPOKEN:
        text = text.replace(pattern, replacement)
    return text


def _confirmation(
    verdict: Verdict, deletions: tuple[str, ...], threshold: int
) -> Confirmation | None:
    """Ask for assent only when a listener would want to have been asked."""
    reasons: list[str] = []
    if deletions:
        reasons.append(f"{_count(len(deletions), 'file')} would be deleted")
    if verdict.status.severity >= Status.ESCALATE.severity:
        reasons.append("verification escalated this change")
    removed = [f for f in verdict.findings if "removed" in f.detail]
    if len(removed) >= threshold:
        reasons.append(f"{_count(len(removed), 'assertion')} would be removed")

    if not reasons:
        return None

    token = _token(verdict, deletions)
    return Confirmation(
        token=token,
        question=(
            f"This needs your confirmation because {_join(reasons)}. "
            f"Say the word {token} to continue, or say cancel."
        ),
        reasons=tuple(reasons),
    )


def _token(verdict: Verdict, deletions: tuple[str, ...]) -> str:
    """Pick a word from the change itself: deterministic, and specific to it.

    No randomness — the same change always asks for the same word, so the
    behaviour is reproducible and testable (RULES.md section 4).
    """
    digest = hashlib.blake2b(digest_size=8)
    digest.update(verdict.to_json().encode("utf-8"))
    for name in sorted(deletions):
        digest.update(name.encode("utf-8"))
    return _WORDS[int.from_bytes(digest.digest(), "big") % len(_WORDS)]


def _spoken_path(path: str) -> str:
    """`tests/test_invoice.py` -> `test invoice`. Directories and extensions are noise."""
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[0].replace("_", " ").replace("-", " ").strip() or path


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


def _join(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + f" and {items[-1]}"
