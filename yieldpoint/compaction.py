"""Source/feedback size comparison for one recorded verification.

This does not measure replaced agent context. It compares submitted source with
the deterministic prescription using a character-based token estimate. Actual
lossless tool-output compaction is implemented separately in context.py.
"""

from __future__ import annotations

from dataclasses import dataclass

from .ledger import CHARS_PER_TOKEN


@dataclass(frozen=True)
class Compaction:
    """The compacted feedback for one turn, or an inapplicable clean turn."""

    source_tokens: int = 0
    compacted_tokens: int = 0

    @property
    def applicable(self) -> bool:
        return bool(self.compacted_tokens)

    @property
    def saved_tokens(self) -> int:
        """Net tokens avoided; a negative value means the feedback is longer."""
        return self.source_tokens - self.compacted_tokens

    @property
    def ratio(self) -> float:
        """Source tokens per feedback token; zero means no feedback was needed."""
        return ratio(self.source_tokens, self.compacted_tokens)


def ratio(source_tokens: int, compacted_tokens: int) -> float:
    """Source tokens per feedback token, or zero when nothing was prescribed.

    Shared because three call sites need the same quotient and the same answer
    for the empty case. Two copies of a ratio drift into two different claims.
    """
    if not compacted_tokens:
        return 0.0
    return source_tokens / compacted_tokens


def estimate_tokens(characters: int) -> int:
    """Round a non-zero piece of text up to one estimated token."""
    return (max(0, characters) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN


def compact(analysed_chars: int, prescription_chars: int) -> Compaction:
    """Describe the prompt replacement for one turn.

    A clean verdict has no prescription and therefore no replacement to claim
    as a compaction.  It deliberately reports as inapplicable rather than as a
    zero-token prompt or a perfect saving.
    """
    if prescription_chars <= 0:
        return Compaction()
    return Compaction(
        source_tokens=estimate_tokens(analysed_chars),
        compacted_tokens=estimate_tokens(prescription_chars),
    )


__all__ = ["Compaction", "compact", "estimate_tokens", "ratio"]
