"""Semantic loop detection.

LangGraph's ``recursion_limit`` counts supersteps and raises at N regardless of
whether progress is being made. That stops runaway graphs but cannot tell a loop
that is converging from one that is stuck — it is a clock, not a progress
measure.

This module detects *the same state recurring*: identical proposed content
producing identical findings means the last iteration achieved nothing, however
many tokens it cost.

The history lives in graph state rather than in an object, because checkpointed
and distributed runs do not preserve instance attributes. Every function here is
pure.
"""

from __future__ import annotations

import hashlib

HISTORY_KEY = "yieldpoint_history"

DEFAULT_WINDOW = 6
DEFAULT_MAX_REPEATS = 3


def signature(*parts: str) -> str:
    """A stable fingerprint of one attempt. No randomness, no clock."""
    # SHA-256 is available in Python, Node and the JDK without an extra
    # dependency. Keeping this fingerprint portable lets every binding detect
    # the same stalled proposal rather than implementing its own loop rule.
    digest = hashlib.sha256()
    for part in parts:
        digest.update((part or "").encode("utf-8", "replace"))
        digest.update(b"\x00")
    return digest.hexdigest()[:24]


def observe(
    history: list[str] | tuple[str, ...] | None,
    current: str,
    *,
    window: int = DEFAULT_WINDOW,
    max_repeats: int = DEFAULT_MAX_REPEATS,
) -> tuple[list[str], bool]:
    """Record an attempt and report whether the loop has stopped progressing.

    Returns the trimmed history and whether ``current`` has now occurred
    ``max_repeats`` times inside the window.
    """
    recent = list(history or [])[-(window - 1) if window > 1 else 0:] + [current]
    tripped = recent.count(current) >= max_repeats
    return recent, tripped


def repeats(history: list[str] | tuple[str, ...] | None, current: str) -> int:
    return list(history or []).count(current)
