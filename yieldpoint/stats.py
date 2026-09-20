"""Turning the ledger into the answer to "is this actually helping?".

The report is deliberately in three blocks, and the headings say which kind of
number each holds. A reader who only trusts the first block still gets a
complete, honest picture; a reader who wants the cost comparison can see exactly
which assumption it rests on.

What is *not* claimed here: that an agent using Yieldpoint converges in fewer
total model calls. That needs a benchmark against a real model, it does not
exist yet, and this says so plainly. The counterfactual below is narrower and
defensible — it prices the *critique*, which Yieldpoint
produces for nothing and an LLM-as-judge produces for one call.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .ledger import Event


@dataclass(frozen=True)
class Summary:
    """Counted facts. Every field here is measured, none is inferred."""

    verdicts: int = 0
    findings: int = 0
    rules: tuple[tuple[str, int], ...] = ()
    statuses: tuple[tuple[str, int], ...] = ()
    surfaces: tuple[tuple[str, int], ...] = ()
    prescription_chars: int = 0
    analysed_chars: int = 0

    prescribed_chars: int = 0
    """Analysed characters from the verdicts that actually produced a critique.

    Separate from ``analysed_chars`` because the two answer different questions.
    A clean verdict contributes characters to the first and nothing to the
    second, so dividing the pooled totals credits the critique with describing
    code it never mentioned — and the more clean verdicts a ledger holds, the
    better that ratio looks. See ``compaction``."""
    files_checked: int = 0
    files_skipped: int = 0
    total_ms: int = 0
    median_ms: int = 0
    p95_ms: int = 0

    severities: tuple[tuple[str, int], ...] = ()
    confidences: tuple[tuple[str, int], ...] = ()
    languages: tuple[tuple[str, int], ...] = ()
    agents: tuple[tuple[str, int], ...] = ()
    """Findings per agent, for a fan-out. Empty when nobody set YIELDPOINT_AGENT."""

    runs: int = 0
    """Distinct orchestrated jobs represented in this ledger."""

    hotspots: tuple[tuple[str, int], ...] = ()
    """Files with the most findings. Where the debt actually is."""

    acknowledged: int = 0
    """Findings answered by a source comment. Visible so suppression cannot rot."""

    resolved: int = 0
    """Findings that were gone the next time their file was analysed."""

    recurring: int = 0
    """Findings still present in the most recent look at their file."""

    @property
    def caught(self) -> int:
        """Verdicts that reported something. The times it earned its place."""
        return sum(count for status, count in self.statuses
                   if status not in ("pass", "unverified"))

    @property
    def contract_findings(self) -> int:
        """Findings that mean the test suite lost strength, as opposed to shape."""
        return sum(count for rule, count in self.rules if rule in CONTRACT_RULES)

    @property
    def blocking_grade(self) -> int:
        """Findings derived exactly, and therefore permitted to block."""
        return sum(count for name, count in self.confidences if name == "exact")

    @property
    def fix_rate(self) -> float:
        """Share of findings gone by the next look. An observation, not a proof."""
        seen = self.resolved + self.recurring
        return self.resolved / seen if seen else 0.0

    @property
    def unverified_rate(self) -> float:
        """Share of files nothing could analyse. The honesty metric."""
        total = self.files_checked + self.files_skipped
        return self.files_skipped / total if total else 0.0

    @property
    def compaction(self) -> float:
        """Analysed characters per prescription character, on comparable work.

        How much smaller the instruction is than the code it describes. The
        numerator counts only the verdicts that produced a critique: a file
        nothing was said about is not code the critique compressed, and
        including it inflates the ratio in proportion to how much clean code
        happened to be verified alongside (RULES.md section 5).

        0.0 when nothing was prescribed.
        """
        if not self.prescription_chars:
            return 0.0
        return self.prescribed_chars / self.prescription_chars


#: Rules that mean the suite lost verification strength rather than shape.
CONTRACT_RULES = frozenset({
    "assertion_monotonicity", "vacuous_assertion",
    "empty_test", "skip_marker", "disabled_assertion",
})


def summarise(events: list[Event]) -> Summary:
    """Fold the ledger into one Summary. Every field here is measured."""
    if not events:
        return Summary()
    resolved, recurring = _outcomes(events)
    return Summary(
        verdicts=len(events),
        resolved=resolved,
        recurring=recurring,
        **_sums(events),
        **_timings(events),
        **_groupings(events),
    )


def _sums(events: list[Event]) -> dict:
    """Plain totals across every event."""
    return {
        "findings": sum(e.findings for e in events),
        "prescription_chars": sum(e.prescription_chars for e in events),
        "analysed_chars": sum(e.analysed_chars for e in events),
        "prescribed_chars": sum(
            e.analysed_chars for e in events if e.prescription_chars),
        "files_checked": sum(e.files_checked for e in events),
        "files_skipped": sum(e.files_skipped for e in events),
        "acknowledged": sum(e.acknowledged for e in events),
    }


def _timings(events: list[Event]) -> dict:
    """Total, median and 95th percentile, from the sorted durations."""
    durations = sorted(e.duration_ms for e in events)
    last = len(durations) - 1
    return {
        "total_ms": sum(durations),
        "median_ms": durations[len(durations) // 2],
        "p95_ms": durations[min(last, int(len(durations) * 0.95))],
    }


def _groupings(events: list[Event]) -> dict:
    """Every "by X" breakdown the report offers."""
    rules = _rule_counts(events)
    return {
        "rules": tuple(sorted(rules.items(), key=lambda kv: (-kv[1], kv[0]))),
        "statuses": tuple(sorted(Counter(e.status for e in events).items())),
        "surfaces": tuple(sorted(Counter(e.surface for e in events).items())),
        "severities": _tally(events, "severities"),
        "confidences": _tally(events, "confidences"),
        "languages": _tally(events, "languages"),
        "agents": _by_agent(events),
        "runs": len({e.run for e in events if e.run}),
        "hotspots": _hotspots(events),
    }


def _tally(events: list[Event], field_name: str) -> tuple[tuple[str, int], ...]:
    counts: Counter = Counter()
    for event in events:
        counts.update(getattr(event, field_name))
    return tuple(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def _by_agent(events: list[Event], limit: int = 10) -> tuple[tuple[str, int], ...]:
    """Findings attributed to each worker, worst first."""
    counts: Counter = Counter()
    for event in events:
        if event.agent:
            counts[event.agent] += event.findings
    return tuple(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit])


def _hotspots(events: list[Event], limit: int = 5) -> tuple[tuple[str, int], ...]:
    counts: Counter = Counter()
    for event in events:
        for key in event.keys:
            counts[key.split("::")[0]] += 1
    return tuple(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit])


def _outcomes(events: list[Event]) -> tuple[int, int]:
    """Split findings into those later absent and those still there.

    A finding counts as resolved when its file was analysed again afterwards
    and the finding was gone. Files never looked at again are counted as
    neither — silence is not evidence of a fix.

    This is an *observation*, not a measurement of cause: something fixed the
    finding, and it need not have been Yieldpoint. Reported as such.
    """
    latest_for_file: dict[str, set] = {}
    for event in events:
        for path in event.checked:
            latest_for_file[path] = set(event.keys)

    ever: set = set()
    for event in events:
        ever.update(event.keys)

    resolved = recurring = 0
    for key in ever:
        path = key.split("::")[0]
        last = latest_for_file.get(path)
        if last is None:
            continue
        if key in last:
            recurring += 1
        else:
            resolved += 1
    return resolved, recurring


def _rule_counts(events: list[Event]) -> Counter:
    counts: Counter = Counter()
    for event in events:
        counts.update(event.rules)
    return counts


__all__ = ["Summary", "summarise", "CONTRACT_RULES"]
