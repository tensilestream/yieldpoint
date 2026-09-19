"""Assertion monotonicity: did this change weaken what the tests verify?

The check is a **domination test over subjects**, not a count. For every subject
asserted before the change, the after state must still assert something about it
at equal or greater strength.

That formulation is what separates tampering from refactoring. Counting
assertions flags a parametrised rewrite that merges five tests into one;
domination does not, because every subject survives. Conversely it catches a
downgrade that leaves the count identical, which is exactly the edit coverage
cannot see.

Comparison is file-level by design: moving an assertion between tests, renaming
its test, splitting or merging tests all preserve subjects, so none of them
register. Moves *between files* are handled by the caller passing
``also_covered`` with subjects found elsewhere in the same change set.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .accessor import normalize
from .decomposition import covered
from .assertions import Extraction, TestCase
from .relation import Relation
from .subject import generalize

#: Minimum similarity for two differently-named tests to be considered the same.
PAIR_THRESHOLD = 0.5

REMOVED = "removed"
"""The subject is gone, and the test that asserted it is still here. Deleting an
assertion out of a surviving test is not how anyone moves code."""

TEST_REMOVED = "test_removed"
"""The whole test that asserted it is gone from this file. Indistinguishable —
from a single edit — from the first step of moving that test somewhere else,
which is why a single-edit gate defers this one and a change-set check does not."""

DOWNGRADED = "downgraded"
DISABLED = "disabled"


@dataclass(frozen=True)
class Weakening:
    """One subject that lost verification strength."""

    subject: str
    before: Relation
    after: Relation
    kind: str
    test: str
    line: int
    source: str = ""

    @property
    def detail(self) -> str:
        if self.kind == TEST_REMOVED:
            return (
                f"{self.test or 'The test'} asserted {self.subject} and is no "
                "longer in this file."
            )
        if self.kind == REMOVED:
            return f"Assertion on {self.subject} was removed."
        if self.kind == DISABLED:
            return (
                f"Assertion on {self.subject} can no longer fail "
                "(unreachable, or its exception is swallowed)."
            )
        return (
            f"Assertion on {self.subject} was weakened: "
            f"{self.before.value} -> {self.after.value}."
        )

    @property
    def prescription(self) -> str:
        restore = f" Restore `{self.source}`." if self.source else ""
        if self.kind == DISABLED:
            return (
                f"Make the assertion on {self.subject} able to fail again: remove the "
                f"swallowing handler or the unreachable guard.{restore}"
            )
        return (
            f"Re-assert {self.subject} at {self.before.value} strength, or fix the code "
            f"under test so the original assertion passes.{restore}"
        )


def subject_map(extraction: Extraction) -> dict[str, Relation]:
    """Strongest effective relation per subject across every test in the file."""
    strongest: dict[str, Relation] = {}
    for test in extraction.tests:
        for subject, relation in test.subjects.items():
            current = strongest.get(subject)
            if current is None or relation.rank > current.rank:
                strongest[subject] = relation
    return strongest


def fallback_key(subject: str, params=(), *, accessors: bool = True, aliases=()) -> str:
    """The key used when exact matching fails.

    Composes the normalisations that describe the same verification written
    differently: parametrisation (``calc(1)`` and ``calc(n)``), accessors
    (``inv.total`` and ``inv.getTotal()``), ``await``, and local variable names
    (``result = compute()`` and ``outcome = compute()``).
    """
    return generalize(
        normalize(subject) if accessors else subject, params, dict(aliases)
    )


def generalized_map(
    extraction: Extraction, *, accessors: bool = True
) -> dict[str, Relation]:
    """Subject map keyed by fallback form, to survive rewrites that preserve meaning."""
    strongest: dict[str, Relation] = {}
    for test in extraction.tests:
        for subject, relation in test.subjects.items():
            key = fallback_key(
                subject, test.params, accessors=accessors, aliases=test.aliases
            )
            current = strongest.get(key)
            if current is None or relation.rank > current.rank:
                strongest[key] = relation
    return strongest


def compare(
    before: Extraction,
    after: Extraction,
    *,
    also_covered: Mapping[str, Relation] | None = None,
    accessors: bool = True,
) -> tuple[Weakening, ...]:
    """Return every subject that lost strength between ``before`` and ``after``.

    ``also_covered`` lets a caller supply subjects verified elsewhere in the same
    change set, so relocating a test to another file is not reported as loss.
    ``accessors`` treats a property and its getter as one subject.
    """
    if not before.ok or not after.ok:
        return ()

    resolver = _Resolver(
        before=before,
        exact=subject_map(after),
        general=generalized_map(after, accessors=accessors),
        extra=dict(also_covered or {}),
        accessors=accessors,
    )
    pairs = pair_tests(before, after)

    findings = []
    for subject, before_relation in sorted(subject_map(before).items()):
        weakening = _weakening(subject, before_relation, resolver, pairs, after)
        if weakening is not None:
            findings.append(weakening)
    return tuple(findings)


def _weakening(subject, before_relation, resolver, pairs, after):
    """The finding for one subject, or ``None`` when it is still verified."""
    if not before_relation.verifies_anything:
        return None

    owner, assertion = _owner(resolver.before, subject)
    if assertion is not None and covered(
        subject, assertion.expected, before_relation, resolver.exact
    ):
        return None

    after_relation, present = resolver.find(subject)
    kind = _kind(before_relation, after_relation, present)
    if kind is None:
        return None
    if kind is REMOVED and owner is not None and owner.qualname not in after.by_name:
        kind = TEST_REMOVED

    return Weakening(
        subject=subject,
        before=before_relation,
        after=after_relation,
        kind=kind,
        test=owner.qualname if owner else "",
        line=_report_line(owner, assertion, pairs, after),
        source=assertion.raw if assertion else "",
    )


def _kind(before: Relation, after: Relation, present: bool) -> str | None:
    """How the subject lost strength, or ``None`` if it did not."""
    if not present:
        return REMOVED
    if not after.verifies_anything:
        return DISABLED
    if after.descends_from(before):
        return DOWNGRADED
    return None


def pair_tests(before: Extraction, after: Extraction) -> dict[str, str]:
    """Map before-test names to after-test names, by name then by structure."""
    pairs = {t.qualname: t.qualname for t in before.tests if t.qualname in after.by_name}

    unmatched_before = [t for t in before.tests if t.qualname not in pairs]
    taken = set(pairs.values())
    unmatched_after = [t for t in after.tests if t.qualname not in taken]

    scored = sorted(
        (
            (_similarity(b, a), b.qualname, a.qualname)
            for b in unmatched_before
            for a in unmatched_after
        ),
        key=lambda item: (-item[0], item[1], item[2]),
    )
    for score, before_name, after_name in scored:
        if score < PAIR_THRESHOLD:
            break
        if before_name in pairs or after_name in taken:
            continue
        pairs[before_name] = after_name
        taken.add(after_name)
    return pairs


def _similarity(before: TestCase, after: TestCase) -> float:
    if before.body_hash and before.body_hash == after.body_hash:
        return 1.0
    left = {fallback_key(s, before.params, aliases=before.aliases) for s in before.subjects}
    right = {fallback_key(s, after.params, aliases=after.aliases) for s in after.subjects}
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


@dataclass(frozen=True)
class _Resolver:
    """Everything needed to answer "is this subject still verified?".

    One object rather than five arguments threaded through each lookup: the
    three maps and the accessor flag are always passed together, and a function
    taking all of them separately is over the parameter limit this project
    enforces on everyone else.
    """

    before: Extraction
    exact: Mapping[str, Relation]
    general: Mapping[str, Relation]
    extra: Mapping[str, Relation]
    accessors: bool = True

    def find(self, subject: str) -> tuple[Relation, bool]:
        """Resolve a subject in the after state: exact, elsewhere, then normalised.

        Exact first keeps precision; the normalised fallback only ever
        suppresses a finding that exact matching would have raised, never
        invents one.
        """
        if subject in self.exact:
            return self.exact[subject], True
        if subject in self.extra:
            return self.extra[subject], True

        owner, _ = _owner(self.before, subject)
        key = fallback_key(
            subject,
            owner.params if owner else (),
            accessors=self.accessors,
            aliases=owner.aliases if owner else (),
        )
        if key in self.general:
            return self.general[key], True
        return Relation.NONE, False


def _owner(extraction: Extraction, subject: str):
    """The test and assertion that asserted ``subject`` most strongly."""
    best_test = None
    best_assertion = None
    for test in extraction.tests:
        for assertion in test.assertions:
            if assertion.subject != subject:
                continue
            if best_assertion is None or assertion.effective.rank > best_assertion.effective.rank:
                best_test, best_assertion = test, assertion
    return best_test, best_assertion


def _report_line(owner, assertion, pairs: Mapping[str, str], after: Extraction) -> int:
    """Point at the after-state test when it still exists, else the old location."""
    if owner is not None:
        paired = after.by_name.get(pairs.get(owner.qualname, ""))
        if paired is not None:
            return paired.line
    return assertion.line if assertion is not None else 0
