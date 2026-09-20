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
from .compaction import compact, ratio


@dataclass(frozen=True)
class Totals:
    """The running aggregate the footer needs. Deliberately four numbers.

    Anything richer belongs in ``yieldpoint stats``, which people run
    occasionally and can afford to read the whole file for.
    """

    verdicts: int = 0
    caught: int = 0
    findings: int = 0
    analysed_chars: int = 0
    prescribed_chars: int = 0
    prescription_chars: int = 0
    compaction_source_tokens: int = 0
    compacted_tokens: int = 0

    @property
    def compaction(self) -> float:
        """Input tokens per feedback token for repair turns, or zero if none."""
        return ratio(self.compaction_source_tokens, self.compacted_tokens)


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
        stat = target.stat()
        size = stat.st_size
    except OSError:
        return _fold(Totals(), _previous(target))

    generation = [stat.st_dev, stat.st_ino, _generation(Path(str(target) + ".1"))]
    offset, running, previous_mtime = _cached(cache, generation)
    if offset > size or (offset == size and previous_mtime != stat.st_mtime_ns):
        offset, running = 0, Totals()
    if offset == 0:
        running = _fold(Totals(), _previous(target))

    try:
        with target.open("rb") as handle:
            handle.seek(offset)
            raw = handle.read()
            consumed = offset + len(raw)
    except (OSError, ValueError):
        return running

    # A final line without its newline is a write still in flight. Leave it for
    # next time rather than counting half an event.
    if raw and not raw.endswith(b"\n"):
        cut = raw.rfind(b"\n")
        if cut == -1:
            return running
        consumed = offset + cut + 1
        raw = raw[: cut + 1]

    fresh = raw.decode("utf-8", errors="replace")
    running = _fold(running, fresh)
    _store(cache, consumed, running, generation, stat.st_mtime_ns)
    return running



def _fold(running: Totals, text: str) -> Totals:
    verdicts = caught = findings = analysed = prescribed = prescription = 0
    source_tokens = compacted_tokens = 0
    from .events import parse_events
    for event in parse_events(text):
        if event.context is not None:
            continue
        verdicts += 1
        findings += event.findings
        analysed += event.analysed_chars
        output = event.prescription_chars
        prescription += output
        if output:
            prescribed += event.analysed_chars
            item = compact(event.analysed_chars, output)
            source_tokens += item.source_tokens
            compacted_tokens += item.compacted_tokens
        if event.status not in ("pass", "unverified"):
            caught += 1
    return Totals(
        verdicts=running.verdicts + verdicts,
        caught=running.caught + caught,
        findings=running.findings + findings,
        analysed_chars=running.analysed_chars + analysed,
        prescribed_chars=running.prescribed_chars + prescribed,
        prescription_chars=running.prescription_chars + prescription,
        compaction_source_tokens=running.compaction_source_tokens + source_tokens,
        compacted_tokens=running.compacted_tokens + compacted_tokens,
    )


def _generation(path: Path):
    try:
        stat = path.stat()
        return [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns]
    except OSError:
        return None


def _previous(target: Path) -> str:
    try:
        return Path(str(target) + ".1").read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def _cached(cache: Path, generation) -> tuple[int, Totals, int]:
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
        if data.get("version") != 3 or data.get("generation") != generation:
            return 0, Totals(), 0
        offset = data["offset"]
        if type(offset) is not int or offset < 0:
            raise ValueError("invalid cache offset")
        values = data["totals"]
        if not all(type(value) is int and value >= 0 for value in values.values()):
            raise ValueError("invalid cache totals")
        return offset, Totals(**values), data["mtime"]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return 0, Totals(), 0


def _store(cache: Path, offset: int, running: Totals, generation, mtime: int) -> None:
    """Replace the cache atomically. Best effort: losing it costs one full read."""
    temp = cache.with_suffix(f".{os.getpid()}.tmp")
    try:
        temp.write_text(
            json.dumps({"version": 3, "generation": generation, "mtime": mtime,
                        "offset": offset, "totals": asdict(running)}),
            encoding="utf-8",
        )
        os.replace(str(temp), str(cache))
    except OSError:
        try:
            temp.unlink()
        except OSError:
            pass


__all__ = ["Totals", "totals"]
