"""Whether this change introduced a violation or inherited one.

The rules in structure.py already refuse to fire on debt a change did not
touch. What they did not do is *say* which of the two happened. A file that
grew by one line was reported as "has 1386 lines of code, over the limit of
300" — true, and read by everyone as an accusation about 1386 lines rather
than about one.

That difference is the whole adoption question for a repository with history.
"You made this worse by one line" and "you wrote a 1386-line file" call for
different reactions, and a tool that renders them identically trains people to
acknowledge everything.

Pure arithmetic over two measurements. No clock, no git, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass

#: This change created the violation: the measure was within its limit before.
INTRODUCED = "introduced"

#: The violation predates the change, which made it worse.
WORSENED = "worsened"

#: Over the limit, and this change did not move it. Never worth stopping for.
CARRIED = "carried"

#: Over the limit and heading down. Reported, because "still over" is true, but
#: the direction is the useful fact.
IMPROVING = "improving"

#: Within the limit. No finding.
CLEAR = "clear"

#: Nothing to compare against — a new file, an unreadable parent revision, a
#: rename git did not follow. Distinct from ``INTRODUCED`` on purpose: a file
#: with no history is not evidence that this change wrote it (RULES.md
#: section 5 — a check that could not run must not report a result).
UNCLASSIFIED = "unclassified"


@dataclass(frozen=True)
class Baseline:
    """One measure, now and before, against the limit it must respect."""

    after: int
    limit: int
    before: int | None = None

    @property
    def classification(self) -> str:
        if not self.limit or self.after <= self.limit:
            return CLEAR
        if self.before is None:
            return UNCLASSIFIED
        if self.before <= self.limit:
            return INTRODUCED
        if self.after > self.before:
            return WORSENED
        return IMPROVING if self.after < self.before else CARRIED

    @property
    def over(self) -> bool:
        """Whether a finding is warranted at all."""
        return self.classification not in (CLEAR,)

    @property
    def added(self) -> int:
        """What this change contributed, which is rarely the whole number."""
        return 0 if self.before is None else self.after - self.before

    def describe(self, subject: str, measure: str) -> str:
        """The finding's detail line, naming who is responsible for what."""
        kind = self.classification
        if kind == WORSENED:
            return (f"{subject} grew from {self.before:,} to {self.after:,} "
                    f"{measure} (+{self.added:,}). It was already over the "
                    f"limit of {self.limit:,} before this change.")
        if kind == UNCLASSIFIED:
            return (f"{subject} has {self.after:,} {measure}, over the limit of "
                    f"{self.limit:,}. Nothing to compare against, so whether "
                    f"this change introduced it is not known.")
        return (f"{subject} has {self.after:,} {measure}, over the limit of "
                f"{self.limit:,}.")


#: Appended to a rule's own advice when the limit was already breached. The
#: advice stays correct — the file still wants splitting, the function still
#: wants shortening — but whose debt it is changes what a reader should do
#: about it inside the task they were actually given.
INHERITED_NOTE = ("It was already over before this change, so the fix is owed "
                  "but is not this change's debt. At a minimum, do not add to it.")


__all__ = ["Baseline", "INHERITED_NOTE", "INTRODUCED", "WORSENED", "CARRIED", "IMPROVING",
           "CLEAR", "UNCLASSIFIED"]
