"""The running total, folded incrementally instead of recomputed.

Split from ledger.py because it answers a different question. That file records
what happened; this one keeps a cheap running answer to "how much so far", which
the footer asks on every single verdict.

That frequency is the whole design constraint. Reading the entire ledger each
time costs O(events) per call and O(events squared) over a session — invisible
with twenty events on a laptop, ruinous with three hundred agents appending all
day. So the fold is cached beside the ledger with the byte offset it covers, and
each call reads only what was appended since.

The cache is advisory in both directions. It is written with an atomic replace,
so a concurrent writer cannot produce a torn file; and it is distrusted on read,
so a missing, stale, corrupt or rotated-underneath cache costs one full read
rather than a wrong number.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from .ledger import DEFAULT_PATH


@dataclass(frozen=True)
class Totals:
    """The running aggregate the footer needs. Deliberately four numbers.

    Anything richer belongs in ``aegisflow stats``, which people run
    occasionally and can afford to read the whole file for.
    """

    verdicts: int = 0
    caught: int = 0
    findings: int = 0
    analysed_chars: int = 0


def totals(path: str | Path = DEFAULT_PATH) -> Totals:
    """Running totals, folded incrementally rather than recomputed.

    The footer rides along with every verdict, so this runs on every call. Doing
    it by reading the whole ledger each time costs O(events) per call and
    therefore O(events squared) over a session — which is invisible on a laptop
    with twenty events and ruinous with three hundred agents appending all day.

    So the fold is cached beside the ledger with the byte offset it covers, and
    each call reads only what was appended since. The cache is advisory: if it
    is missing, stale, corrupt, or the ledger has been rotated underneath it,
    the whole file is read and the cache rebuilt. Being wrong is impossible;
    being slow once is the worst case.
    """
    target = Path(path)
    cache = Path(str(target) + ".totals.json")
    try:
        size = target.stat().st_size
    except OSError:
        return Totals()

    offset, running = _cached(cache)
    if offset > size:
        offset, running = 0, Totals()  # rotated or truncated: start again

    try:
        with target.open("r", encoding="utf-8") as handle:
            handle.seek(offset)
            fresh = handle.read()
            consumed = offset + len(fresh.encode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return running

    # A final line without its newline is a write still in flight. Leave it for
    # next time rather than counting half an event.
    if fresh and not fresh.endswith("\n"):
        cut = fresh.rfind("\n")
        consumed -= len(fresh[cut + 1:].encode("utf-8"))
        fresh = fresh[: cut + 1]

    running = _fold(running, fresh)
    _store(cache, consumed, running)
    return running


def _fold(running: Totals, text: str) -> Totals:
    verdicts = caught = findings = analysed = 0
    for line in text.splitlines():
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        verdicts += 1
        findings += int(data.get("findings", 0))
        analysed += int(data.get("analysed_chars", 0))
        if data.get("status") not in ("pass", "unverified"):
            caught += 1
    return Totals(
        verdicts=running.verdicts + verdicts,
        caught=running.caught + caught,
        findings=running.findings + findings,
        analysed_chars=running.analysed_chars + analysed,
    )


def _cached(cache: Path) -> tuple[int, Totals]:
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
        return int(data["offset"]), Totals(**data["totals"])
    except (OSError, ValueError, KeyError, TypeError):
        return 0, Totals()


def _store(cache: Path, offset: int, running: Totals) -> None:
    """Replace the cache atomically. Best effort: losing it costs one full read."""
    temp = cache.with_suffix(f".{os.getpid()}.tmp")
    try:
        temp.write_text(
            json.dumps({"offset": offset, "totals": asdict(running)}),
            encoding="utf-8",
        )
        os.replace(str(temp), str(cache))
    except OSError:
        try:
            temp.unlink()
        except OSError:
            pass


__all__ = ["Totals", "totals"]
