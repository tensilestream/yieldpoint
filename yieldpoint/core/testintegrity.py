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
from .relation import Relation

#: Tokens that mark a call as assertion-like even when its exact spelling is
#: unknown. A body full of these is a style we do not read, not an empty test.
_ASSERTION_TOKENS = ("assert", "expect", "should", "verify", "check", "must", "ensure")

VACUOUS_ASSERTION = "vacuous_assertion"
DISABLED_ASSERTION = "disabled_assertion"
SKIP_MARKER = "skip_marker"
EMPTY_TEST = "empty_test"
WEAK_NEW_TEST = "weak_new_test"

#: Relations that constrain almost nothing on their own. A *new* test whose
#: every assertion sits here has not been weakened — it arrived weak, which
#: monotonicity cannot see because there is no before state to compare against.
#: This is the shape an agent produces when asked to "add the feature with
#: tests": the code is new, the test is new, and nothing ever pinned a value.
_WEAK_RELATIONS = frozenset({Relation.NON_NULL, Relation.TRUTHY})


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
    known = {test.qualname for test in before.tests} if before.ok else set()
    return tuple(
        o for o in inspect(after)
        if o.key not in existing and not _already_reported(o, known)
    )


def _already_reported(offence: Offence, known: set[str]) -> bool:
    """Is this offence about a test that already existed?

    Only ``weak_new_test`` cares. A test that *was* strong and is now weak has
    been weakened, and monotonicity says so precisely — naming the subject and
    the strength it lost. Reporting it twice, once vaguely, buries the useful
    message under the useless one.
    """
    return offence.rule == WEAK_NEW_TEST and offence.test in known


def _looks_like_assertions(calls: tuple[str, ...]) -> bool:
    lowered = " ".join(calls).lower()
    return any(token in lowered for token in _ASSERTION_TOKENS)


def _weak_new_test(test: TestCase) -> Offence | None:
    """A test that verifies only that something exists.

    Deliberately narrow. It fires only when *every* assertion in the test is
    weak: one exact check alongside a not-null guard is a normal test, and
    flagging it would make the rule noise. An opaque call is treated as
    unknown strength, so a test delegating to a helper is left alone.
    """
    assertions = [a for a in test.assertions if a.effective.verifies_anything]
    if not assertions:
        return None                       # empty_test and the others own this
    if any(a.effective not in _WEAK_RELATIONS for a in assertions):
        return None

    weakest = ", ".join(sorted({a.effective.value for a in assertions}))
    return Offence(
        rule=WEAK_NEW_TEST,
        test=test.qualname,
        line=test.line,
        detail=(f"`{test.qualname}` is new and only checks {weakest}: it passes "
                "for any value the code happens to return."),
        prescription=(
            f"Assert the value {test.qualname} is supposed to produce, not that "
            "it exists. A not-null check passes whether the calculation is "
            "right or wrong."
        ),
        key=f"{WEAK_NEW_TEST}:{test.qualname}",
        source=assertions[0].raw,
    )


def _skipped(test: TestCase) -> Offence | None:
    if not test.skip_markers:
        return None
    markers = ", ".join(test.skip_markers)
    return Offence(
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


def _empty(test: TestCase) -> Offence | None:
    """Nothing in the body, or nothing that can fail.

    The second case fires only when there is nothing else to point at. A test
    whose assertions are all vacuous or all disabled is reported by those
    rules, which are specific. And never when the body is full of calls that
    read like assertions in a style this build does not recognise — accusing a
    whole project of writing empty tests is how a tool gets muted.
    """
    if test.is_empty:
        return Offence(
            rule=EMPTY_TEST, test=test.qualname, line=test.line,
            detail=f"{test.qualname} has no body and verifies nothing.",
            prescription=f"Give {test.qualname} assertions, or remove it.",
            key=f"{EMPTY_TEST}:{test.qualname}",
        )
    if test.assertions or _looks_like_assertions(test.unclassified_calls):
        return None
    return Offence(
        rule=EMPTY_TEST, test=test.qualname, line=test.line,
        detail=f"{test.qualname} runs code but asserts nothing.",
        prescription=f"Add an assertion to {test.qualname} that can fail.",
        key=f"{EMPTY_TEST}:{test.qualname}",
    )


def _unfailable(test: TestCase, assertion) -> Offence | None:
    """An assertion that is a tautology, or whose failure cannot propagate."""
    if assertion.relation.value == "vacuous":
        return Offence(
            rule=VACUOUS_ASSERTION, test=test.qualname, line=assertion.line,
            detail=f"`{assertion.raw}` is a tautology and can never fail.",
            prescription=(
                "Assert something about the value under test, or delete the line. "
                "A tautology makes the suite green without verifying anything."
            ),
            key=f"{VACUOUS_ASSERTION}:{test.qualname}:{assertion.subject}",
            source=assertion.raw,
        )
    if not assertion.reachable and assertion.relation.verifies_anything:
        return Offence(
            rule=DISABLED_ASSERTION, test=test.qualname, line=assertion.line,
            detail=(f"`{assertion.raw}` cannot fail: it is unreachable, or its "
                    "exception is swallowed."),
            prescription=(
                "Remove the swallowing handler or the unreachable guard so this "
                "assertion can fail again."
            ),
            key=f"{DISABLED_ASSERTION}:{test.qualname}:{assertion.subject}",
            source=assertion.raw,
        )
    return None


def _for_test(test: TestCase) -> list[Offence]:
    """Every offence one test exhibits, in the order a reader wants them."""
    found = [
        offence for offence in
        (_weak_new_test(test), _skipped(test), _empty(test))
        if offence is not None
    ]
    found.extend(
        offence for offence in
        (_unfailable(test, a) for a in test.assertions)
        if offence is not None
    )
    return found
