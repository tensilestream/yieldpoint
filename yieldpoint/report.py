"""Presenting the ledger: the report, and the line that rides along with it.

Separate from stats.py because the two change for different reasons — that file
grows when there is a new thing worth counting, this one when there is a better
way to say it. Splitting them is also what kept stats.py under the limit this
project enforces on everyone else.

The shape of the report is the argument. Three headed blocks, never blended:
what was *measured*, what is true *architecturally*, and what is *estimated*
from measured bytes — plus a block naming what is deliberately not claimed.
A reader who trusts only the first block still gets a complete picture.
"""

from __future__ import annotations

from .ledger import CHARS_PER_TOKEN
from .stats import Summary

def render(summary: Summary) -> str:
    """The human report, one block per kind of number."""
    if not summary.verdicts:
        return (
            "No verifications recorded yet.\n\n"
            "Run `yieldpoint review` or let the hook see an edit, then try again.\n"
            "Recording is local only and is switched off with\n"
            '  "metrics": { "enabled": false }   in .yieldpoint.json'
        )

    return "\n".join([
        *_measured(summary), "",
        *_architectural(summary), "",
        *_estimated(summary),
    ])


def _measured(summary: Summary) -> list[str]:
    out = ["MEASURED — counted from what actually ran", ""]
    out += _coverage(summary)
    out += _quality(summary)
    out += _effectiveness(summary)
    return out


def _coverage(summary: Summary) -> list[str]:
    out = [
        "  Coverage",
        f"    verifications                {summary.verdicts:>8,}",
        f"    files analysed               {summary.files_checked:>8,}",
        f"    files nothing could analyse  {summary.files_skipped:>8,}"
        f"   ({summary.unverified_rate:.0%})",
    ]
    if summary.languages:
        rendered = ", ".join(f"{name} {count:,}" for name, count in summary.languages[:6])
        out.append(f"    by file type                 {rendered}")
    if summary.surfaces:
        rendered = ", ".join(f"{name} {count:,}" for name, count in summary.surfaces)
        out.append(f"    by surface                   {rendered}")
    if summary.runs:
        out.append(f"    orchestrated runs            {summary.runs:>8,}")
    if summary.agents:
        out.append("    findings per agent")
        for name, count in summary.agents:
            out.append(f"      {name:<30} {count:>6,}")
    return out + [""]


def _quality(summary: Summary) -> list[str]:
    out = [
        "  What it caught",
        f"    verdicts reporting something {summary.caught:>8,}",
        f"    findings                     {summary.findings:>8,}",
        f"    of those, test-contract      {summary.contract_findings:>8,}"
        "   (the suite lost strength)",
        f"    of those, exact confidence   {summary.blocking_grade:>8,}"
        "   (only these may block)",
        f"    acknowledged in source       {summary.acknowledged:>8,}"
        "   (# yieldpoint: allow <rule> - reason)",
    ]
    for rule, count in summary.rules:
        out.append(f"      {rule:<28} {count:>6,}")
    if summary.severities:
        rendered = ", ".join(f"{name} {count:,}" for name, count in summary.severities)
        out.append(f"    by severity                  {rendered}")
    if summary.confidences:
        rendered = ", ".join(f"{name} {count:,}" for name, count in summary.confidences)
        out.append(f"    by confidence                {rendered}")
    if summary.hotspots:
        out.append("    most-flagged files")
        for path, count in summary.hotspots:
            out.append(f"      {path:<40} {count:>4,}")
    return out + [""]


def _effectiveness(summary: Summary) -> list[str]:
    out = [
        "  Outcome",
        f"    findings gone by next look   {summary.resolved:>8,}",
        f"    still present                {summary.recurring:>8,}",
    ]
    if summary.resolved or summary.recurring:
        out.append(f"    observed fix rate            {summary.fix_rate:>7.0%}")
        out.append("      An observation, not a cause: something fixed them, and it")
        out.append("      need not have been Yieldpoint. Files never analysed again")
        out.append("      are counted as neither — silence is not evidence of a fix.")
    out += [
        "",
        "  Latency",
        f"    total                        {_ms(summary.total_ms):>8}",
        f"    median per verdict           {_ms(summary.median_ms):>8}",
        f"    95th percentile              {_ms(summary.p95_ms):>8}",
    ]
    return out


def _architectural(summary: Summary) -> list[str]:
    out = [
        "ARCHITECTURAL — true by construction, not measured",
        f"  model calls made by Yieldpoint          {0:>10,}",
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


def running_line(totals) -> str:
    """The one-line total, from the incremental fold rather than a full read."""
    if not totals.verdicts:
        return ""
    judge_tokens = totals.analysed_chars // CHARS_PER_TOKEN
    return (
        f"Yieldpoint so far: {_plural(totals.verdicts, 'check')} · "
        f"{totals.caught:,} flagged · {_plural(totals.findings, 'finding')} · "
        f"0 model calls · ~{_short(judge_tokens)} tokens an LLM judge would "
        f"have read (est.)"
    )


def footer(summary: Summary) -> str:
    """One line, for appending to whatever the agent is already reading.

    The report exists, and nobody runs a second command to find out whether the
    first one was worth it. So the running total rides along with every verdict:
    what has been checked, what was caught, and what the critique cost.

    Empty when nothing has been recorded, so a first run is not decorated with
    a row of zeros.
    """
    if not summary.verdicts:
        return ""
    judge_tokens = summary.analysed_chars // CHARS_PER_TOKEN
    return (
        f"Yieldpoint so far: {_plural(summary.verdicts, 'check')} · "
        f"{summary.caught:,} flagged · {_plural(summary.findings, 'finding')} · "
        f"0 model calls · ~{_short(judge_tokens)} tokens an LLM judge would "
        f"have read (est.)"
    )


def _plural(count: int, noun: str) -> str:
    return f"{count:,} {noun}" + ("" if count == 1 else "s")


def _short(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.0f}k"
    return str(value)


def _ms(value: int) -> str:
    if value < 1000:
        return f"{value} ms"
    return f"{value / 1000:.1f} s"


def _architectural_dict(summary: Summary) -> dict:
    """What is true by construction, plus how the ratio was derived.

    The basis is stated in the payload rather than left to the reader: pooling
    clean verdicts into the numerator inflates it, and a consumer cannot tell
    which convention produced a bare number.
    """
    return {
        "model_calls_made": 0,
        "prescriptions_assembled": summary.findings,
        "compaction_ratio": round(summary.compaction, 1),
        "_compaction_basis": "prescribed_chars / prescription_chars; "
                             "clean verdicts are excluded from the numerator",
        "prescribed_chars": summary.prescribed_chars,
        "prescription_chars": summary.prescription_chars,
    }


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
            "p95_ms": summary.p95_ms,
            "by_severity": dict(summary.severities),
            "by_confidence": dict(summary.confidences),
            "by_language": dict(summary.languages),
            "hotspots": dict(summary.hotspots),
            "agents": dict(summary.agents),
            "runs": summary.runs,
            "contract_findings": summary.contract_findings,
            "acknowledged": summary.acknowledged,
            "exact_confidence_findings": summary.blocking_grade,
            "unverified_rate": round(summary.unverified_rate, 3),
        },
        "observed": {
            "_note": "inference from the ledger, not proof of cause",
            "findings_resolved": summary.resolved,
            "findings_recurring": summary.recurring,
            "fix_rate": round(summary.fix_rate, 3),
        },
        "architectural": _architectural_dict(summary),
        "estimated": {
            "assumption": f"{CHARS_PER_TOKEN} characters per token",
            "llm_judge_model_calls": summary.verdicts,
            "llm_judge_input_tokens": summary.analysed_chars // CHARS_PER_TOKEN,
        },
        "not_claimed": [
            "fewer total model calls to convergence; unbenchmarked",
        ],
    }



__all__ = ["render", "footer", "running_line", "to_dict"]
