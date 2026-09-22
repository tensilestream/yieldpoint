"""Thresholds measured from a repository rather than asserted at it.

The review asked for language-aware defaults: *"300 is tight for a Java service
class, generous for a Go file."* True, and a table of per-language numbers
would still be somebody's opinion wearing a lab coat. The repository in front
of you already knows what its files look like.

So `init` measures before it proposes, and says what it measured:

    1,204 Python files; median 148 lines, p90 612, longest 2,396.
    A limit of 300 would put 41% of this repository over it.

That last sentence is the one that decides adoption. A limit 41% of the tree
already breaks is a limit nobody turns on. A limit a tenth of it breaks is a
ratchet — it bites where the code is worst and leaves the rest alone.

Nothing here reads a clock or a network. The same tree proposes the same
numbers.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .core.metrics import measure
from .core.policy import Policy

#: The share of files a proposed limit is allowed to leave over it. Not zero:
#: a limit nothing breaks enforces nothing, and the point of a starting
#: threshold is to catch the worst tenth and ratchet down from there.
OVER = 0.10

#: Below this there is not enough to generalise from, and a measured proposal
#: would be a rounded accident.
ENOUGH = 12


@dataclass(frozen=True)
class Measured:
    """One measure across a repository."""

    name: str
    values: tuple[int, ...]

    @property
    def enough(self) -> bool:
        return len(self.values) >= ENOUGH

    def at(self, share: float) -> int:
        """The value this share of files sits at or below."""
        if not self.values:
            return 0
        ordered = sorted(self.values)
        index = min(len(ordered) - 1, int(len(ordered) * share))
        return ordered[index]

    @property
    def median(self) -> int:
        return self.at(0.5)

    @property
    def longest(self) -> int:
        return max(self.values) if self.values else 0

    def over(self, limit: int) -> float:
        """The share that would breach ``limit`` today."""
        if not self.values or not limit:
            return 0.0
        return sum(1 for v in self.values if v > limit) / len(self.values)

    @property
    def proposal(self) -> int:
        """A limit that leaves roughly ``OVER`` of the repository over it."""
        return _round(self.at(1 - OVER))


def _round(value: int) -> int:
    """To something a human would have typed, so the number reads as a choice."""
    for step in (50, 100, 250):
        if value <= step * 10:
            return max(step, ((value + step - 1) // step) * step)
    return ((value + 499) // 500) * 500


def survey(root: str | Path = ".", policy: Policy | None = None) -> Measured:
    """File lengths across every Python file the policy would analyse."""
    from .scan import walk

    resolved = policy or Policy()
    lengths = []
    for path in walk(Path(root), resolved):
        try:
            module = measure(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, UnicodeDecodeError):
            continue
        if module.ok:
            lengths.append(module.code_lines)
    return Measured("file length", tuple(lengths))


def describe(found: Measured) -> str:
    """What was measured and what follows from it, in the order a reader needs."""
    if not found.values:
        return "No Python files found, so no limit was measured."
    if not found.enough:
        return (f"Only {len(found.values)} Python file(s) — too few to measure a "
                f"limit from. Left off; set structure.max_file_lines when the "
                f"shape of the project is clearer.")
    proposal = found.proposal
    return (f"{len(found.values):,} Python files; median {found.median:,} lines, "
            f"p90 {found.at(0.9):,}, longest {found.longest:,}.\n"
            f"  A limit of {proposal:,} leaves {found.over(proposal):.0%} of this "
            f"repository over it, and 300 would leave {found.over(300):.0%}.")


__all__ = ["Measured", "survey", "describe", "OVER", "ENOUGH"]
