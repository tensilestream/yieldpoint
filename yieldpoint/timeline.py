"""The ledger with its time axis kept.

``stats`` folds every event into one Summary, which answers "what has this been
worth" and destroys "when". Both questions are real: a total tells you whether
to keep the tool, and a per-turn line tells you which turn cost you something
and whether the trend is going the right way.

The two savings columns are **not the same kind of number**, and are labelled
apart here exactly as they are in ``report.py``:

*Calls* is architectural. Yieldpoint makes no model call, and an LLM-as-judge
producing the same critique makes one per verdict. That is a property of how
each is built, not an observation.

*Tokens* is estimated — measured characters divided by a stated constant. Real
tokenizers disagree, so it is an order of magnitude and never a bill.

Nothing here is inferred beyond those two, and neither is blended into the
other. RULES.md section 5 is why.
"""

from __future__ import annotations

import sys
import time
from dataclasses import asdict, dataclass

from .compaction import compact
from .ledger import CHARS_PER_TOKEN, Event


@dataclass(frozen=True)
class Turn:
    """One verification, with the running totals as of that moment."""

    at: int
    surface: str
    status: str
    findings: int
    duration_ms: int
    analysed_chars: int
    prescription_chars: int
    run: str = ""
    agent: str = ""

    files: tuple[str, ...] = ()
    """What this verdict analysed. Kept so repeated analysis of the same set is
    visible: without it the totals read as distinct work when they are not."""

    #: Architectural: one judge call per verdict, avoided by construction.
    calls_saved: int = 1
    #: Estimated: what a judge would have read, at CHARS_PER_TOKEN.
    tokens_saved: int = 0

    cum_verdicts: int = 0
    cum_findings: int = 0
    cum_calls_saved: int = 0
    cum_tokens_saved: int = 0

    compacted_tokens: int = 0
    """Estimated feedback tokens for this repair turn; zero when clean."""

    compaction_source_tokens: int = 0
    compaction_saved_tokens: int = 0
    compaction_ratio: float = 0.0
    cum_compaction_ratio: float = 0.0

    @property
    def compared(self) -> bool:
        """Whether this turn produced feedback there was anything to compare.

        A clean verdict prescribes nothing, so no source was replaced by
        anything. The token columns have no value to report for it — which is
        different from reporting a value of zero.
        """
        return bool(self.compacted_tokens)

    @property
    def when(self) -> str:
        """Local wall-clock, because the reader is sitting in a timezone."""
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.at))

    def to_dict(self) -> dict:
        data = asdict(self)
        data["when"] = self.when
        data["savings_basis"] = "legacy *_saved fields are hypothetical judge/feedback comparisons, not observed savings"
        # Without this a reader cannot tell a clean turn's zero from a measured
        # one. The renderer prints a dash; machines get the same fact as a flag.
        data["compared"] = self.compared
        return data


def timeline(events) -> tuple[Turn, ...]:
    """Fold events into per-turn rows, oldest first, carrying the totals."""
    ordered = sorted((e for e in events if e.context is None), key=lambda e: (e.at, e.surface))
    verdicts = findings = calls = tokens = 0
    compacted = compacted_source = 0
    rows = []
    for event in ordered:
        saved_tokens = event.analysed_chars // CHARS_PER_TOKEN
        verdicts += 1
        findings += event.findings
        calls += 1
        tokens += saved_tokens
        turn_compaction = compact(event.analysed_chars, event.prescription_chars)
        if turn_compaction.applicable:
            compacted_source += turn_compaction.source_tokens
            compacted += turn_compaction.compacted_tokens
        rows.append(Turn(
            at=event.at,
            surface=event.surface,
            status=event.status,
            findings=event.findings,
            duration_ms=event.duration_ms,
            analysed_chars=event.analysed_chars,
            prescription_chars=event.prescription_chars,
            run=event.run,
            agent=event.agent,
            files=tuple(event.checked),
            calls_saved=1,
            tokens_saved=saved_tokens,
            cum_verdicts=verdicts,
            cum_findings=findings,
            cum_calls_saved=calls,
            cum_tokens_saved=tokens,
            compaction_source_tokens=turn_compaction.source_tokens,
            compacted_tokens=turn_compaction.compacted_tokens,
            compaction_saved_tokens=turn_compaction.saved_tokens,
            compaction_ratio=turn_compaction.ratio,
            cum_compaction_ratio=(compacted_source / compacted if compacted else 0.0),
        ))
    return tuple(rows)


#: How many rows the terminal shows. The ledger can hold thousands; a wall of
#: them buries the totals underneath, which is what the reader came for.
RECENT = 12


def cost(tokens: int, price_per_million: float) -> float:
    """Currency for a token count, at a rate the caller states."""
    return tokens * price_per_million / 1_000_000


def _money(amount: float) -> str:
    """Small amounts keep their cents; large ones do not need them."""
    return f"{amount:,.2f}" if amount < 1000 else f"{amount:,.0f}"


#: Status to palette attribute. A repair costs you a turn; a block stops you.
_TINT = {"repair": "amber", "escalate": "red", "block": "red", "unverified": "red"}


def repetition(turns: tuple[Turn, ...]) -> tuple[int, int]:
    """``(distinct file sets, verifications that re-ran one already counted)``.

    The totals are honest arithmetic — a judge really would have read each of
    these. But a reader assumes a large number means a lot of *different* code,
    and on a repository where the same suite is verified all day it mostly does
    not. This is what lets the report say so.
    """
    seen: dict[tuple[str, ...], int] = {}
    for turn in turns:
        seen[turn.files] = seen.get(turn.files, 0) + 1
    return len(seen), sum(count - 1 for count in seen.values())


def _figures(last: Turn, price_per_million: float) -> list[tuple[str, str, str]]:
    """``(value, what it is, which tier it belongs to)``, never blended."""
    rows = [
        (f"{last.cum_calls_saved:,}", "hypothetical judge calls", "assumed"),
        (f"~{last.cum_tokens_saved:,}", "hypothetical judge tokens", "estimated"),
    ]
    if price_per_million > 0:
        money = cost(last.cum_tokens_saved, price_per_million)
        rows.append((f"~${_money(money)}",
                     f"at ${price_per_million:,.2f} per M tokens", "your stated rate"))
    return rows


def panel(turns: tuple[Turn, ...], price_per_million: float = 0.0, paint=None) -> str:
    """The headline: what this has been worth, in the tiers it is worth it in.

    Deliberately not one blended number. Calls avoided is architectural and
    exact; tokens is an estimate; money is that estimate times a rate the reader
    supplied, printed back so the arithmetic is theirs to check. Formatting the
    values before padding keeps the column aligned — a leading ``~`` outside the
    field width is the classic way to make a proud number look sloppy.
    """
    if not turns:
        return ""
    paint = paint or _palette()
    last = turns[-1]
    rule = f"{paint.steel}{'─' * 64}{paint.reset}"
    big = f"{paint.bold}{paint.amber}"

    rows = _figures(last, price_per_million)

    distinct, repeats = repetition(turns)

    lines = [
        rule,
        f"  {paint.bold}JUDGE COMPARISON{paint.reset}  {paint.dim}on this repository, across "
        f"{last.cum_verdicts:,} verification(s){paint.reset}",
        "",
    ]
    lines += [
        f"  {big}{value:>14}{paint.reset}   {label:<26}{paint.dim}{tier}{paint.reset}"
        for value, label, tier in rows
    ]
    if price_per_million <= 0:
        lines.append(f"  {paint.dim}{'':>14}   set metrics.price_per_million for a "
                     f"cost estimate{paint.reset}")
    if repeats:
        # Without this the total reads as distinct work. A judge really would
        # have read every one of these, so the figure is not wrong — but a
        # reader will assume it counts different code each time, and here it
        # mostly does not. Saying so is cheaper than being caught not saying it.
        lines.append("")
        lines.append(
            f"  {paint.dim}over {distinct:,} distinct file set(s); {repeats:,} "
            f"verification(s) re-analysed one already counted{paint.reset}")
    lines.append(rule)
    return "\n".join(lines)


def render(turns: tuple[Turn, ...], limit: int = RECENT,
           price_per_million: float = 0.0, paint=None) -> str:
    """The per-turn table, most recent last, under the headline panel."""
    if not turns:
        return ""
    paint = paint or _palette()
    shown = turns[-limit:]
    lines = [
        panel(turns, price_per_million, paint),
        "",
        f"{paint.bold}PER TURN{paint.reset}  {paint.dim}when each verdict happened, "
        f"and the running total after it{paint.reset}",
        f"  {paint.dim}{'when':<19}  {'surface':<8} {'status':<10} "
        f"{'found':>5} {'ms':>6} {'input':>7} {'feedback':>9} {'delta':>7} {'ratio':>7}"
        f"  feedback ratio so far{paint.reset}",
    ]
    for turn in shown:
        tint = getattr(paint, _TINT.get(turn.status, "steel"))
        found = f"{turn.findings:>5}"
        lines.append(
            f"  {turn.when:<19}  {turn.surface:<8} "
            f"{tint}{turn.status:<10}{paint.reset} "
            f"{tint if turn.findings else paint.dim}{found}{paint.reset} "
            f"{paint.dim}{turn.duration_ms:>6}{paint.reset} "
            f"{_tokens(turn.compaction_source_tokens, turn.compared):>7} "
            f"{paint.amber}{_tokens(turn.compacted_tokens, turn.compared):>9}{paint.reset}"
            f" {_tokens(turn.compaction_saved_tokens, turn.compared):>7}"
            f" {paint.amber}{_ratio(turn.compaction_ratio):>7}{paint.reset}"
            f"  {paint.dim}{_compaction_label(turn.cum_compaction_ratio)} on repair turns{paint.reset}"
        )
    if len(turns) > len(shown):
        lines.append(f"  {paint.dim}… {len(turns) - len(shown):,} earlier turn(s) not "
                     f"shown; `yieldpoint export` has every one{paint.reset}")
    lines.append("")
    lines.append(f"  {paint.dim}input/feedback — source and prescription tokens. "
                 f"A clean turn prescribes nothing, so it shows — rather than a "
                 f"count. All token counts use {CHARS_PER_TOKEN} chars/token.{paint.reset}")
    return "\n".join(lines)


def _tokens(value: int, compared: bool) -> str:
    """A token count, or a dash when this turn had nothing to compare.

    Printing ``0`` here states a measurement that was never taken. It is the
    same defect as reporting `pass` on a file no rule could read: the reader
    cannot tell an absent comparison from a comparison that found nothing
    (RULES.md section 5).
    """
    return f"{value:,}" if compared else "—"


def _ratio(value: float) -> str:
    """A ratio label that does not turn an inapplicable clean turn into zero."""
    return f"{value:.1f}x" if value else "—"


def _compaction_label(value: float) -> str:
    """Describe a compaction ratio without calling an expansion a saving."""
    if not value:
        return "—"
    if value >= 1:
        return f"{value:.1f}x smaller"
    return f"{1 / value:.1f}x larger"


def _palette():
    """Colour for stdout, or empty strings when it is not a terminal."""
    from .branding import palette

    return palette(sys.stdout)


__all__ = ["Turn", "timeline", "render", "panel", "cost", "repetition",
           "RECENT"]
