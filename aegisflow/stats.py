"""Turning the ledger into the answer to "is this actually helping?".

The report is deliberately in three blocks, and the headings say which kind of
number each holds. A reader who only trusts the first block still gets a
complete, honest picture; a reader who wants the cost comparison can see exactly
which assumption it rests on.

What is *not* claimed here: that an agent using AegisFlow converges in fewer
total model calls. That needs a benchmark against a real model, it does not
exist yet, and PLAN_AND_POSITIONING.md section 4.1 says so. The counterfactual
below is narrower and defensible — it prices the *critique*, which AegisFlow
produces for nothing and an LLM-as-judge produces for one call.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .ledger import CHARS_PER_TOKEN, Event


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
    files_checked: int = 0
    files_skipped: int = 0
    total_ms: int = 0
    median_ms: int = 0

    @property
    def caught(self) -> int:
        """Verdicts that reported something. The times it earned its place."""
        return sum(count for status, count in self.statuses
                   if status not in ("pass", "unverified"))

    @property
    def compaction(self) -> float:
        """Analysed characters per prescription character.

        How much smaller the instruction is than the code it describes — the
        honest version of "prompt compaction". 0.0 when nothing was prescribed.
        """
        if not self.prescription_chars:
            return 0.0
        return self.analysed_chars / self.prescription_chars


def summarise(events: list[Event]) -> Summary:
    if not events:
        return Summary()
    durations = sorted(e.duration_ms for e in events)
    rules = _rule_counts(events)
    return Summary(
        verdicts=len(events),
        findings=sum(e.findings for e in events),
        rules=tuple(sorted(rules.items(), key=lambda kv: (-kv[1], kv[0]))),
        statuses=tuple(sorted(Counter(e.status for e in events).items())),
        surfaces=tuple(sorted(Counter(e.surface for e in events).items())),
        prescription_chars=sum(e.prescription_chars for e in events),
        analysed_chars=sum(e.analysed_chars for e in events),
        files_checked=sum(e.files_checked for e in events),
        files_skipped=sum(e.files_skipped for e in events),
        total_ms=sum(durations),
        median_ms=durations[len(durations) // 2],
    )


def _rule_counts(events: list[Event]) -> Counter:
    counts: Counter = Counter()
    for event in events:
        counts.update(event.rules)
    return counts


def render(summary: Summary) -> str:
    """The human report, one block per kind of number."""
    if not summary.verdicts:
        return (
            "No verifications recorded yet.\n\n"
            "Run `aegisflow review` or let the hook see an edit, then try again.\n"
            "Recording is local only and is switched off with\n"
            '  "metrics": { "enabled": false }   in .aegisflow.json'
        )

    return "\n".join([
        *_measured(summary), "",
        *_architectural(summary), "",
        *_estimated(summary),
    ])


def _measured(summary: Summary) -> list[str]:
    out = [
        "MEASURED — counted from what actually ran",
        f"  verifications          {summary.verdicts:>10,}",
        f"  reported something     {summary.caught:>10,}",
        f"  findings               {summary.findings:>10,}",
        f"  files checked          {summary.files_checked:>10,}",
        f"  files not analysed     {summary.files_skipped:>10,}",
        f"  time in verification   {_ms(summary.total_ms):>10}"
        f"   (median {_ms(summary.median_ms)} per verdict)",
    ]
    if summary.rules:
        out.append("")
        out.append("  what it caught")
        for rule, count in summary.rules:
            out.append(f"    {rule:<26} {count:>6,}")
    return out


def _architectural(summary: Summary) -> list[str]:
    out = [
        "ARCHITECTURAL — true by construction, not measured",
        f"  model calls made by AegisFlow          {0:>10,}",
        f"  prescriptions assembled, not generated {summary.findings:>10,}",
        f"  characters of critique produced free   {summary.prescription_chars:>10,}",
    ]
    if summary.compaction:
        out.append(f"  {_compaction_line(summary.compaction)}")
    return out


def _compaction_line(ratio: float) -> str:
    """How the critique compares in size to the code it describes.

    Stated in whichever direction is true. On a small change the prescription is
    legitimately *larger* than the code analysed, and rounding that to "0x
    smaller" would be a nonsense number dressed as a win.
    """
    if ratio >= 1:
        return f"critique is {ratio:,.1f}x smaller than the code it describes"
    return (
        f"critique is {1 / ratio:,.1f}x larger than the code analysed"
        " — expected when changes are small"
    )


def _estimated(summary: Summary) -> list[str]:
    judge_calls = summary.verdicts
    judge_tokens = summary.analysed_chars // CHARS_PER_TOKEN
    return [
        "ESTIMATED — arithmetic on the measured bytes above",
        "  If an LLM-as-judge had produced the same critiques:",
        f"    model calls                          {judge_calls:>10,}"
        "   (one per verdict, by construction)",
        f"    input tokens                        ~{judge_tokens:>10,}"
        f"   ({summary.analysed_chars:,} chars / {CHARS_PER_TOKEN})",
        "",
        f"  The token figure divides measured characters by {CHARS_PER_TOKEN}. Real",
        "  tokenizers disagree; treat it as an order of magnitude, not a bill.",
        "",
        "NOT CLAIMED",
        "  That your agent converges in fewer total model calls. That needs a",
        "  benchmark against a real model, and it does not exist yet.",
    ]


def _ms(value: int) -> str:
    if value < 1000:
        return f"{value} ms"
    return f"{value / 1000:.1f} s"


def to_dict(summary: Summary) -> dict:
    """The machine-readable form, tiered the same way as the report."""
    return {
        "measured": {
            "verdicts": summary.verdicts,
            "reported_something": summary.caught,
            "findings": summary.findings,
            "by_rule": dict(summary.rules),
            "by_status": dict(summary.statuses),
            "by_surface": dict(summary.surfaces),
            "files_checked": summary.files_checked,
            "files_skipped": summary.files_skipped,
            "prescription_chars": summary.prescription_chars,
            "analysed_chars": summary.analysed_chars,
            "total_ms": summary.total_ms,
            "median_ms": summary.median_ms,
        },
        "architectural": {
            "model_calls_made": 0,
            "prescriptions_assembled": summary.findings,
            "compaction_ratio": round(summary.compaction, 1),
        },
        "estimated": {
            "assumption": f"{CHARS_PER_TOKEN} characters per token",
            "llm_judge_model_calls": summary.verdicts,
            "llm_judge_input_tokens": summary.analysed_chars // CHARS_PER_TOKEN,
        },
        "not_claimed": [
            "fewer total model calls to convergence; unbenchmarked",
        ],
    }


__all__ = ["Summary", "summarise", "render", "to_dict"]
