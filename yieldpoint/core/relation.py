"""The assertion strength lattice.

An assertion's *relation* is what it constrains about its subject. Relations form
a **partial** order, not a total one: ``x > 5`` and ``x in [1, 2, 3]`` constrain
different things and neither is stronger. Pretending otherwise would let the
engine report confident nonsense, so incomparability is represented explicitly
and always resolves in favour of silence.
"""

from __future__ import annotations

from enum import Enum


class Relation(str, Enum):
    """What an assertion pins down about its subject, strongest first."""

    EQ = "eq"
    """Exact value or identity: ``x == 3``, ``x is None``, ``assertEqual``."""

    COMPARISON = "comparison"
    """Bounds the value: ``x > 5``, ``x != 3``, ``assertGreater``."""

    MEMBERSHIP = "membership"
    """Constrains to a set: ``x in xs``, ``assertIn``, ``isinstance``."""

    RAISES = "raises"
    """Constrains behaviour: ``pytest.raises``, ``assertRaises``."""

    OPAQUE = "opaque"
    """A call whose assertions live elsewhere: ``assert_valid_invoice(x)``.
    Strength is unknown, so it is comparable with nothing (see :meth:`dominates`)."""

    TRUTHY = "truthy"
    """``assert x``, ``assertTrue`` — passes for any non-falsey value."""

    NON_NULL = "non_null"
    """``assert x is not None``, ``assertIsNotNone`` — the weakest real check."""

    VACUOUS = "vacuous"
    """``assert True``, ``expect(true).toBe(true)`` — constrains nothing."""

    NONE = "none"
    """No assertion, or one whose failure cannot propagate."""

    # ------------------------------------------------------------------ order

    @property
    def rank(self) -> int:
        return _RANK[self]

    @property
    def verifies_anything(self) -> bool:
        return _RANK[self] > 0

    def dominates(self, other: "Relation") -> bool | None:
        """Is ``self`` at least as strong as ``other``?

        Returns ``None`` when the two are **incomparable** — either because one is
        :attr:`OPAQUE` (unknown strength) or because they constrain different
        dimensions at equal strength. Callers must treat ``None`` as "no finding":
        a false negative is recoverable, a false positive costs trust
        (RULES.md section 6).
        """
        if self is other:
            return True
        if self is Relation.OPAQUE or other is Relation.OPAQUE:
            return None
        if self in _SIBLINGS and other in _SIBLINGS:
            return None
        return _RANK[self] >= _RANK[other]

    def descends_from(self, other: "Relation") -> bool:
        """True only when ``self`` is *definitely* weaker than ``other``.

        This is the predicate the monotonicity check fires on, so it is
        deliberately conservative: incomparable pairs are not descents.
        """
        return self.dominates(other) is False


_RANK: dict[Relation, int] = {
    Relation.EQ: 5,
    Relation.COMPARISON: 4,
    Relation.MEMBERSHIP: 4,
    Relation.RAISES: 4,
    Relation.OPAQUE: 3,
    Relation.TRUTHY: 2,
    Relation.NON_NULL: 1,
    Relation.VACUOUS: 0,
    Relation.NONE: 0,
}

#: Equal-rank relations constraining different dimensions; mutually incomparable.
_SIBLINGS = frozenset({Relation.COMPARISON, Relation.MEMBERSHIP, Relation.RAISES})
