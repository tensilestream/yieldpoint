"""Selecting part of the ledger: a period, a run, or a worker.

The ledger is append-only and has no idea what a "session" is. That is the
right shape for the file and the wrong shape for the question people actually
ask, which is *what did this afternoon's work produce?*

A session is a window of time, so that is what this selects. ``--run`` and
``--agent`` are the other two axes, for an orchestrated fan-out where the
interesting grouping is which job or which worker rather than when.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

#: Suffix to seconds. Deliberately small: a period nobody can spell is a
#: period nobody uses.
UNITS = {"m": 60, "h": 3_600, "d": 86_400, "w": 604_800}


class BadWindow(ValueError):
    """The period could not be understood. Better than silently selecting all."""


@dataclass(frozen=True)
class Window:
    """Which events to include."""

    since: int = 0
    run: str = ""
    agent: str = ""

    @property
    def everything(self) -> bool:
        return not (self.since or self.run or self.agent)

    def holds(self, event) -> bool:
        if self.run and event.run != self.run:
            return False
        if self.agent and event.agent != self.agent:
            return False
        if self.since and event.at and event.at < self.since:
            return False
        # An event with no timestamp predates the field. Excluded from a
        # time window rather than assumed recent, because assuming would put
        # old work into today's numbers.
        if self.since and not event.at:
            return False
        return True

    def describe(self) -> str:
        if self.everything:
            return "everything recorded"
        parts = []
        if self.since:
            parts.append(f"since {_ago(self.since)}")
        if self.run:
            parts.append(f"run {self.run}")
        if self.agent:
            parts.append(f"agent {self.agent}")
        return ", ".join(parts)


def parse(since: str = "", run: str = "", agent: str = "",
          now: int | None = None) -> Window:
    """Build a window. Raises :class:`BadWindow` on a period it cannot read."""
    return Window(since=_since(since, now), run=run or "", agent=agent or "")


def _since(text: str, now: int | None) -> int:
    if not text:
        return 0
    moment = int(now if now is not None else time.time())
    lowered = text.strip().lower()

    if lowered == "today":
        return moment - moment % 86_400
    if lowered in ("session", "now"):
        return moment - 8 * 3_600  # a working day's worth, which is what people mean

    unit = lowered[-1:]
    if unit in UNITS and lowered[:-1].isdigit():
        return moment - int(lowered[:-1]) * UNITS[unit]

    raise BadWindow(
        f"cannot read the period {text!r}; try 2h, 30m, 7d, or today"
    )


def apply(events: list, window: Window) -> list:
    return [e for e in events if window.holds(e)] if not window.everything else events


def _ago(moment: int) -> str:
    seconds = max(0, int(time.time()) - moment)
    for suffix, size in (("w", 604_800), ("d", 86_400), ("h", 3_600), ("m", 60)):
        if seconds >= size:
            return f"{seconds // size}{suffix} ago"
    return "just now"


__all__ = ["Window", "BadWindow", "parse", "apply", "UNITS"]
