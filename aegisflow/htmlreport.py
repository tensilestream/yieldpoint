"""A page you can look at, built from the ledger.

Every surface — the CLI, the hook, the MCP server, a LangGraph node — writes to
one ledger, so there is one place that knows what the whole system did. The text
report answers that at a terminal. This answers it for everyone else: a single
file you can open, keep, or attach to a pull request.

**Static, and self-contained.** No server, no build step, no dependency: one
HTML file with its styles inside it. That matters for the same reason the rest
of this package has no dependencies — it has to work inside somebody else's
environment without negotiating.

The three-tier honesty of the text report is preserved exactly. *Measured* is
counted, *architectural* is true by construction, *estimated* carries its
assumption, and what is not claimed is written down rather than omitted.
"""

from __future__ import annotations

import html
from dataclasses import dataclass

from .ledger import CHARS_PER_TOKEN
from .stats import CONTRACT_RULES, Summary

MAX_BAR = 26

_STAR = "<span class='star'>correctness</span>"


@dataclass(frozen=True)
class Now:
    """The state of the working tree right now, not the history of it.

    A page that only totals the past answers "what has this caught?". The
    question someone actually opens a report to answer is "what do I do?", and
    that needs the findings themselves — file, line, and the fix — not counts.
    """

    findings: tuple = ()
    checked: int = 0
    reason: str = ""
    pace: object = None
    """What to do at the next stopping point. A warning, never a stop."""

    @property
    def blocking(self) -> tuple:
        return tuple(f for f in self.findings if f.rule in CONTRACT_RULES)

    @property
    def advisory(self) -> tuple:
        return tuple(f for f in self.findings if f.rule not in CONTRACT_RULES)


@dataclass(frozen=True)
class Page:
    title: str
    """The browser tab and gallery name — carries the product name."""

    summary: Summary
    scope: str = "everything recorded"
    source: str = ""

    now: Now = None
    """What needs attention, if the caller looked. ``None`` when it did not."""

    heading: str = ""
    """What the page says at the top. Defaults to ``title``, but is kept
    separate so the masthead does not print the product name twice: the eyebrow
    above it already says which tool produced this."""

    def shown(self) -> str:
        return self.heading or self.title


def render(page: Page) -> str:
    """One self-contained HTML document."""
    s = page.summary
    if not s.verdicts:
        return _document(page, "<p class='empty'>Nothing recorded yet. "
                               "Run <code>aegisflow review</code>, or let the hook "
                               "see an edit.</p>")
    left = _todo(page.now) or _section(
        "To fix", "nothing outstanding",
        "<p class='empty'>Nothing in the working tree needs attention.</p>")
    right = "".join([
        _section("Measured", "counted from what actually ran", _measured(s)),
        _section("Architectural", "true by construction, not observed",
                 _architectural(s)),
        _section("Estimated", f"arithmetic on the measured bytes, at "
                              f"{CHARS_PER_TOKEN} characters per token", _estimated(s)),
        _section("Not claimed", "stated rather than omitted", _unclaimed()),
    ])
    body = (
        _verdict_banner(page.now)
        + _pace_bar(page.now)
        + _headline(s)
        + f"<div class='split'><div class='col'>{left}</div>"
          f"<div class='col'>{right}</div></div>"
    )
    return _document(page, body)


def _pace_bar(now) -> str:
    """The budget gauge. Advice for the next boundary, not an instruction now."""
    decision = getattr(now, "pace", None)
    if decision is None:
        return ""
    used = float(decision.signals.get("budget_used") or 0)
    state = {"continue": "is-ok", "wrap-up": "is-warn",
             "overdue": "is-over", "fix-first": "is-warn"}.get(decision.value, "is-ok")
    return (
        f"<div class='pace {state}'>"
        f"<div class='pace-top'><b>{html.escape(decision.value)}</b>"
        f"<span class='num'>{decision.signals.get('added_lines', 0):,} / "
        f"{decision.signals.get('limit', 0):,} lines since the last commit</span></div>"
        f"<span class='gauge'><span style='width:{min(1.0, used):.0%}'></span></span>"
        f"<p>{html.escape(decision.reason)}</p></div>"
    )


def _verdict_banner(now) -> str:
    """The first thing on the page: what to do, before any statistics."""
    if now is None:
        return ""
    if now.reason:
        return (f"<div class='verdict is-quiet'><b>Nothing to check.</b>"
                f"<span>{html.escape(now.reason)}</span></div>")
    if now.blocking:
        return (
            f"<div class='verdict is-blocking'>"
            f"<b>{len(now.blocking)} thing(s) to fix before committing</b>"
            f"<span>The test suite lost verification strength. "
            f"{len(now.advisory)} further advisory finding(s).</span></div>"
        )
    if now.advisory:
        return (
            f"<div class='verdict is-advisory'><b>Nothing weakened</b>"
            f"<span>{len(now.advisory)} maintainability finding(s) to consider. "
            f"{now.checked} file(s) checked.</span></div>"
        )
    return (f"<div class='verdict is-clean'><b>Clean</b>"
            f"<span>{now.checked} file(s) checked, nothing to fix.</span></div>")


def _todo(now) -> str:
    """The findings themselves, most serious first, each with its fix."""
    if now is None or not now.findings:
        return ""
    ordered = [*now.blocking, *now.advisory]
    items = []
    for finding in ordered[:20]:
        contract = finding.rule in CONTRACT_RULES
        items.append(
            f"<li class='{'is-blocking' if contract else 'is-advisory'}'>"
            f"<div class='where'><code>{html.escape(finding.location)}</code>"
            f"<span class='rule'>{html.escape(finding.rule)}</span></div>"
            f"<p class='what'>{html.escape(finding.detail)}</p>"
            f"<p class='fix'>{html.escape(finding.prescription)}</p></li>"
        )
    more = (f"<p class='more'>and {len(ordered) - 20} more — "
            f"run <code>aegisflow review</code></p>" if len(ordered) > 20 else "")
    return (f"<section class='todo'><div class='tier-head'><h2>To fix</h2>"
            f"<span class='note'>uncommitted work, most serious first</span></div>"
            f"<ol class='findings'>{''.join(items)}</ol>{more}</section>")


def _headline(s: Summary) -> str:
    cards = [
        ("verifications", f"{s.verdicts:,}", "across every surface"),
        ("findings", f"{s.findings:,}", f"{s.contract_findings:,} of them correctness"),
        ("model calls", "0", "the critique is assembled, not generated"),
        ("median verdict", _ms(s.median_ms), f"95th percentile {_ms(s.p95_ms)}"),
    ]
    return "<div class='cards'>" + "".join(
        f"<div class='card{' is-zero' if value == '0' else ''}'>"
        f"<span class='value'>{html.escape(value)}</span>"
        f"<span class='label'>{html.escape(label)}</span>"
        f"<span class='note'>{html.escape(note)}</span></div>"
        for label, value, note in cards
    ) + "</div>"


def _measured(s: Summary) -> str:
    parts = [
        _bars("What it caught", s.rules, mark=CONTRACT_RULES),
        _bars("Where it ran", s.surfaces),
        _bars("Most-flagged files", s.hotspots),
    ]
    if s.agents:
        parts.append(_bars("Findings per agent", s.agents))
    parts.append(_rows("Coverage", [
        ("files analysed", f"{s.files_checked:,}"),
        ("files nothing could analyse",
         f"{s.files_skipped:,} ({s.unverified_rate:.0%})"),
        ("acknowledged in source", f"{s.acknowledged:,}"),
        ("findings gone by next look",
         f"{s.resolved:,} of {s.resolved + s.recurring:,} ({s.fix_rate:.0%})"),
    ]))
    return "".join(parts)


def _architectural(s: Summary) -> str:
    compaction = (
        f"{s.compaction:,.1f}x smaller than the code it describes"
        if s.compaction >= 1 else
        f"{1 / s.compaction:,.1f}x larger than the code analysed"
    ) if s.compaction else "not applicable"
    return _rows("", [
        ("model calls made by AegisFlow", "0"),
        ("prescriptions assembled, not generated", f"{s.findings:,}"),
        ("characters of critique produced free", f"{s.prescription_chars:,}"),
        ("critique size", compaction),
    ])


def _estimated(s: Summary) -> str:
    return _rows("If an LLM-as-judge had produced the same critiques", [
        ("model calls", f"{s.verdicts:,} (one per verdict, by construction)"),
        ("input tokens",
         f"~{s.analysed_chars // CHARS_PER_TOKEN:,} "
         f"({s.analysed_chars:,} characters / {CHARS_PER_TOKEN})"),
    ])


def _unclaimed() -> str:
    return (
        "<p class='caveat'>That your agent converges in fewer <em>total</em> model "
        "calls. That needs a benchmark against a real model, and it does not exist "
        "yet, so it is not claimed here.</p>"
    )


def _bars(title: str, pairs, mark=frozenset()) -> str:
    if not pairs:
        return ""
    biggest = max(count for _name, count in pairs) or 1
    rows = []
    for name, count in pairs:
        width = max(1, round(MAX_BAR * count / biggest))
        flag = " is-signal" if name in mark else ""
        rows.append(
            f"<tr><th>{html.escape(str(name))}"
            f"{_STAR if flag else ''}</th>"
            f"<td><span class='track'><span class='bar{flag}' "
            f"style='width:{width / MAX_BAR:.0%}'></span></span></td>"
            f"<td class='num'>{count:,}</td></tr>"
        )
    return (f"<h3>{html.escape(title)}</h3>"
            f"<div class='scroll'><table class='bars'>{''.join(rows)}</table></div>")


def _rows(title: str, pairs) -> str:
    head = f"<h3>{html.escape(title)}</h3>" if title else ""
    rows = "".join(
        f"<tr><th>{html.escape(label)}</th>"
        f"<td class='num'>{html.escape(value)}</td></tr>"
        for label, value in pairs
    )
    return f"{head}<table class='rows'>{rows}</table>"


def _section(name: str, note: str, body: str) -> str:
    """One tier. The class carries how much weight the tier deserves."""
    tier = f"tier-{name.split()[0].lower()}"
    return (
        f"<section class='{tier}'><div class='tier-head'>"
        f"<h2>{html.escape(name)}</h2>"
        f"<span class='note'>{html.escape(note)}</span></div>{body}</section>"
    )


def _ms(value: int) -> str:
    return f"{value} ms" if value < 1000 else f"{value / 1000:.1f} s"


def _document(page: Page, body: str) -> str:
    from .pageshell import document

    return document(
        title=page.title, heading=page.shown(), scope=page.scope,
        source=page.source, body=body,
    )


__all__ = ["Page", "render"]
