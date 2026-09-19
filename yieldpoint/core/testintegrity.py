"""Test-contract checks that are not about assertion strength.

Monotonicity asks whether verification got weaker. These rules catch the other
ways a test stops verifying: it is skipped, its body is emptied, its assertions
are tautologies, or its failures cannot propagate.

Every rule is **differential**. An offence already present before the change is
not attributed to this change — otherwise adopting Yieldpoint on an existing
repository would bury the agent in findings it did not cause. A new file has no
before state, so everything in it is new.
"""

from __future__ import annotations

from dataclasses import dataclass

from .assertions import Extraction, TestCase

#: Tokens that mark a call as assertion-like even when its exact spelling is
#: unknown. A body full of these is a style we do not read, not an empty test.
_ASSERTION_TOKENS = ("assert", "expect", "should", "verify", "check", "must", "ensure")

VACUOUS_ASSERTION = "vacuous_assertion"
DISABLED_ASSERTION = "disabled_assertion"
SKIP_MARKER = "skip_marker"
EMPTY_TEST = "empty_test"


@dataclass(frozen=True)
class Offence:
    """One test-contract violation."""

    rule: str
    test: str
    line: int
    detail: str
    prescription: str
    key: str
    source: str = ""


def inspect(extraction: Extraction) -> tuple[Offence, ...]:
    """Every offence present in one state, regardless of how it got there."""
    if not extraction.ok:
        return ()
    found: list[Offence] = []
    for test in extraction.tests:
        found.extend(_for_test(test))
    return tuple(found)


def compare(before: Extraction, after: Extraction) -> tuple[Offence, ...]:
    """Offences introduced by this change, ignoring pre-existing ones."""
    if not after.ok:
        return ()
    existing = {offence.key for offence in inspect(before)}
    return tuple(o for o in inspect(after) if o.key not in existing)


def _looks_like_assertions(calls: tuple[str, ...]) -> bool:
    lowered = " ".join(calls).lower()
    return any(token in lowered for token in _ASSERTION_TOKENS)


def _for_test(test: TestCase) -> list[Offence]:
    found: list[Offence] = []

    if test.skip_markers:
        markers = ", ".join(test.skip_markers)
        found.append(
            Offence(
                rule=SKIP_MARKER,
                test=test.qualname,
                line=test.line,
                detail=f"{test.qualname} is skipped ({markers}).",
                prescription=(
                    f"Remove the skip marker from {test.qualname} and make it pass, or "
                    "delete the test deliberately rather than disabling it."
                ),
                key=f"{SKIP_MARKER}:{test.qualname}",
                source=markers,
            )
        )

    if test.is_empty:
        found.append(
            Offence(
                rule=EMPTY_TEST,
                test=test.qualname,
                line=test.line,
                detail=f"{test.qualname} has no body and verifies nothing.",
                prescription=f"Give {test.qualname} assertions, or remove it.",
                key=f"{EMPTY_TEST}:{test.qualname}",
            )
        )
    elif not test.assertions and not _looks_like_assertions(test.unclassified_calls):
        # Only when there is nothing to point at. A test whose assertions are all
        # vacuous or all disabled is reported by those rules, which are specific.
        # And never when the body is full of calls that read like assertions in a
        # style this build does not recognise — accusing a whole project of
        # writing empty tests is how a tool gets muted.
        found.append(
            Offence(
                rule=EMPTY_TEST,
                test=test.qualname,
                line=test.line,
                detail=f"{test.qualname} runs code but asserts nothing.",
                prescription=f"Add an assertion to {test.qualname} that can fail.",
                key=f"{EMPTY_TEST}:{test.qualname}",
            )
        )

    for assertion in test.assertions:
        if assertion.relation.value == "vacuous":
            found.append(
                Offence(
                    rule=VACUOUS_ASSERTION,
                    test=test.qualname,
                    line=assertion.line,
                    detail=f"`{assertion.raw}` is a tautology and can never fail.",
                    prescription=(
                        "Assert something about the value under test, or delete the line. "
                        "A tautology makes the suite green without verifying anything."
                    ),
                    key=f"{VACUOUS_ASSERTION}:{test.qualname}:{assertion.subject}",
                    source=assertion.raw,
                )
            )
        elif not assertion.reachable and assertion.relation.verifies_anything:
            found.append(
                Offence(
                    rule=DISABLED_ASSERTION,
                    test=test.qualname,
                    line=assertion.line,
                    detail=(
                        f"`{assertion.raw}` cannot fail: it is unreachable, or its "
                        "exception is swallowed."
                    ),
                    prescription=(
                        "Remove the swallowing handler or the unreachable guard so this "
                        "assertion can fail again."
                    ),
                    key=f"{DISABLED_ASSERTION}:{test.qualname}:{assertion.subject}",
                    source=assertion.raw,
                )
            )

    return found
