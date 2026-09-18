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
from .assertions import Extraction, TestCase
from .relation import Relation
from .subject import generalize

#: Minimum similarity for two differently-named tests to be considered the same.
PAIR_THRESHOLD = 0.5

REMOVED = "removed"
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


def fallback_key(subject: str, params=(), *, accessors: bool = True) -> str:
    """The key used when exact matching fails.

    Composes the two normalisations that describe the same verification written
    differently: parametrisation (``calc(1)`` and ``calc(n)``) and accessors
    (``inv.total`` and ``inv.getTotal()``).
    """
    return generalize(normalize(subject) if accessors else subject, params)


def generalized_map(
    extraction: Extraction, *, accessors: bool = True
) -> dict[str, Relation]:
    """Subject map keyed by fallback form, to survive rewrites that preserve meaning."""
    strongest: dict[str, Relation] = {}
    for test in extraction.tests:
        for subject, relation in test.subjects.items():
            key = fallback_key(subject, test.params, accessors=accessors)
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

    before_subjects = subject_map(before)
    after_subjects = subject_map(after)
    after_general = generalized_map(after, accessors=accessors)
    extra = dict(also_covered or {})
    pairs = pair_tests(before, after)

    findings: list[Weakening] = []
    for subject, before_relation in sorted(before_subjects.items()):
        if not before_relation.verifies_anything:
            continue

        after_relation, present = _lookup(
            subject, before, after_subjects, after_general, extra, accessors
        )

        if not present:
            kind = REMOVED
        elif not after_relation.verifies_anything:
            kind = DISABLED
        elif after_relation.descends_from(before_relation):
            kind = DOWNGRADED
        else:
            continue

        owner, assertion = _owner(before, subject)
        findings.append(
            Weakening(
                subject=subject,
                before=before_relation,
                after=after_relation,
                kind=kind,
                test=owner.qualname if owner else "",
                line=_report_line(owner, assertion, pairs, after),
                source=assertion.raw if assertion else "",
            )
        )
    return tuple(findings)


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
    left = {fallback_key(s, before.params) for s in before.subjects}
    right = {fallback_key(s, after.params) for s in after.subjects}
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _lookup(
    subject: str,
    before: Extraction,
    exact: Mapping[str, Relation],
    general: Mapping[str, Relation],
    extra: Mapping[str, Relation],
    accessors: bool = True,
) -> tuple[Relation, bool]:
    """Resolve a subject in the after state: exact, then elsewhere, then normalised.

    Exact first keeps precision; the normalised fallback only ever suppresses a
    finding that exact matching would have raised, never invents one.
    """
    if subject in exact:
        return exact[subject], True
    if subject in extra:
        return extra[subject], True

    owner, _ = _owner(before, subject)
    key = fallback_key(subject, owner.params if owner else (), accessors=accessors)
    if key in general:
        return general[key], True
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
