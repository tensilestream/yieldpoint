"""Delivering part of a result, and saying so in the result itself.

Compaction so far has been *lossless*: the same JSON goes out, minus
whitespace. This is the other kind. A bounded result leaves things out, which
means it can be wrong in a way whitespace removal cannot — the one line that
mattered may be among the ones dropped.

So the rule here is not "shrink it". It is: **whatever is left out is named in
the text the model reads, with a way to get it back.** A truncated result that
does not say it was truncated is indistinguishable from a complete one, and a
model cannot ask for what it does not know is missing. That failure is the same
shape as a test suite that quietly stops asserting.

Nothing here decides *whether* to bound a result. That is the caller's choice,
keyed on which tool produced the output, never guessed from the content.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Lines of a failing test log worth keeping around the failure itself. A
#: traceback is useless cut off at the exception type.
CONTEXT_LINES = 40

#: Markers that mean a line is part of why something failed rather than part of
#: the noise around it. Matched case-insensitively against the whole line.
FAILURE_MARKERS = ("error", "fail", "traceback", "assert", "exception",
                   "no such", "not found", "timeout", "panic")


@dataclass(frozen=True)
class Bounded:
    """One result, reduced, with what was dropped stated as data."""

    text: str
    """What the model reads. Already carries the disclosure line."""

    kept: int = 0
    omitted: int = 0
    original_chars: int = 0

    @property
    def complete(self) -> bool:
        """Whether anything was left out at all."""
        return not self.omitted


def _disclose(omitted: int, handle: str) -> str:
    """The line that makes an omission visible to whoever reads the result."""
    recall = f" Retrieve with: yieldpoint recall {handle}" if handle else ""
    return f"[{omitted:,} more line(s) not shown.{recall}]"


def head(text: str, *, limit: int, handle: str = "") -> Bounded:
    """The first ``limit`` lines, with the rest declared rather than dropped.

    For results whose order carries the ranking — search hits, file listings —
    where the front is the part worth reading and the tail is the long
    diminishing remainder.
    """
    lines = text.splitlines()
    if limit < 0 or len(lines) <= limit:
        return Bounded(text, kept=len(lines), original_chars=len(text))
    omitted = len(lines) - limit
    kept = lines[:limit]
    return Bounded("\n".join([*kept, _disclose(omitted, handle)]),
                   kept=limit, omitted=omitted, original_chars=len(text))


def _interesting(lines: list[str]) -> set[int]:
    """Indices of lines that look like part of a failure, plus their tail."""
    hits = {index for index, line in enumerate(lines)
            if any(marker in line.lower() for marker in FAILURE_MARKERS)}
    if not hits:
        # Nothing announced itself as a failure, so the end of the log is the
        # best guess available — and being a guess, it keeps the disclosure.
        return set(range(max(0, len(lines) - CONTEXT_LINES), len(lines)))
    return hits


def failures(text: str, *, handle: str = "") -> Bounded:
    """The lines that explain a failure, with the rest declared.

    Deliberately generous: a log with no recognisable failure keeps its tail
    rather than being cut to nothing. Guessing wrong about which lines matter
    is recoverable here only because the omission is disclosed.
    """
    lines = text.splitlines()
    wanted = _interesting(lines)
    if len(wanted) >= len(lines):
        return Bounded(text, kept=len(lines), original_chars=len(text))
    keep = sorted(wanted)
    omitted = len(lines) - len(keep)
    body = [lines[index] for index in keep]
    return Bounded("\n".join([*body, _disclose(omitted, handle)]),
                   kept=len(keep), omitted=omitted, original_chars=len(text))


__all__ = ["Bounded", "CONTEXT_LINES", "FAILURE_MARKERS", "failures", "head"]
