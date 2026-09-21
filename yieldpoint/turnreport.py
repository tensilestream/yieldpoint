"""The per-turn table.

Split from timeline.py for the reason brief.py and briefing.py are split: that
file changes when there is a new fact worth recording, this one when there is a
better way to show it.

The selection is the part worth explaining. A pure tail of the ledger answers
"where am I now", and that is not the question anybody opens this to ask. The
steady state of using this tool is: it finds something, you fix it, you re-run
until clean — so the last dozen turns are almost always clean by construction.
A tool whose job is catching things then shows you twelve moments it caught
nothing, and reads as though it has never caught anything at all.

So two blocks: the most recent turns, and the most recent turns that found
something. The second is the one the reader came for.
"""

from __future__ import annotations

from .timeline import (
    CHARS_PER_TOKEN,
    RECENT,
    Turn,
    _compaction_label,
    _palette,
    _ratio,
    _tokens,
    _TINT,
    panel,
)

#: How many past turns with findings to surface alongside the recent ones.
NOTABLE = 6


def _recent(turns: tuple[Turn, ...], limit: int) -> list[Turn]:
    return list(turns[-limit:])


def _notable(turns: tuple[Turn, ...], already: list[Turn], limit: int) -> list[Turn]:
    """The last turns that found something, minus those already on screen."""
    seen = {id(turn) for turn in already}
    found = [t for t in turns if t.findings and id(t) not in seen]
    return found[-limit:]


def _row(turn: Turn, paint) -> str:
    tint = getattr(paint, _TINT.get(turn.status, "steel"))
    return (
        f"  {turn.when:<19}  {turn.surface:<8} "
        f"{tint}{turn.status:<10}{paint.reset} "
        f"{tint if turn.findings else paint.dim}{turn.findings:>5}{paint.reset} "
        f"{paint.dim}{turn.duration_ms:>6}{paint.reset} "
        f"{_tokens(turn.compaction_source_tokens, turn.compared):>7} "
        f"{paint.amber}{_tokens(turn.compacted_tokens, turn.compared):>9}{paint.reset}"
        f" {_tokens(turn.compaction_saved_tokens, turn.compared):>7}"
        f" {paint.amber}{_ratio(turn.compaction_ratio):>7}{paint.reset}"
    )


def _header(paint) -> str:
    return (f"  {paint.dim}{'when':<19}  {'surface':<8} {'status':<10} "
            f"{'found':>5} {'ms':>6} {'input':>7} {'feedback':>9} {'delta':>7} "
            f"{'ratio':>7}{paint.reset}")


def _caught(turns: tuple[Turn, ...], shown: list[Turn], paint) -> list[str]:
    """What this has actually caught, which a tail of clean turns hides."""
    found = [t for t in turns if t.findings]
    if not found:
        return ["", f"  {paint.dim}Nothing has been found in {len(turns):,} "
                    f"turn(s).{paint.reset}"]
    notable = _notable(turns, shown, NOTABLE)
    out = ["", f"{paint.bold}WHAT IT CAUGHT{paint.reset}  {paint.dim}"
               f"{len(found):,} of {len(turns):,} turn(s) found something"
               f"{paint.reset}"]
    if not notable:
        out.append(f"  {paint.dim}the most recent are already listed above"
                   f"{paint.reset}")
        return out
    out.append(_header(paint))
    out.extend(_row(turn, paint) for turn in notable)
    return out


def render(turns: tuple[Turn, ...], limit: int = RECENT,
           price_per_million: float = 0.0, paint=None) -> str:
    """The per-turn table, most recent last, under the headline panel."""
    if not turns:
        return ""
    paint = paint or _palette()
    shown = _recent(turns, limit)
    lines = [
        panel(turns, price_per_million, paint),
        "",
        f"{paint.bold}PER TURN{paint.reset}  {paint.dim}when each verdict happened, "
        f"and the running total after it{paint.reset}",
        _header(paint),
    ]
    lines.extend(_row(turn, paint) for turn in shown)
    if len(turns) > len(shown):
        lines.append(f"  {paint.dim}… {len(turns) - len(shown):,} earlier turn(s) not "
                     f"shown; `yieldpoint export` has every one{paint.reset}")
    lines.extend(_caught(turns, shown, paint))
    lines.append("")
    # Once, not per row. It is a running total, so printing it beside every
    # turn repeated one number down the whole table and read as if it were
    # changing.
    lines.append(f"  {paint.dim}feedback so far: "
                 f"{_compaction_label(turns[-1].cum_compaction_ratio)} on repair "
                 f"turns{paint.reset}")
    lines.append(f"  {paint.dim}input/feedback — source and prescription tokens. "
                 f"A clean turn prescribes nothing, so it shows — rather than a "
                 f"count. All token counts use {CHARS_PER_TOKEN} chars/token.{paint.reset}")
    return "\n".join(lines)


__all__ = ["render", "NOTABLE"]
