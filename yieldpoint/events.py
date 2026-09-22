"""Ledger event schema and defensive decoding, independent of storage."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass

def _split(data: dict) -> int | None:
    """How many findings were inherited, or ``None`` when the row predates it.

    Absent and null both mean the turn was never classified. Zero means it was,
    and nothing was inherited — a trend that read the first as the second would
    invent a split for history that has none.
    """
    value = data.get("inherited")
    return None if value is None else int(value)


@dataclass(frozen=True)
class Event:
    """One verification, reduced to what can be counted."""

    surface: str
    status: str
    findings: int = 0
    rules: tuple[str, ...] = ()
    prescription_chars: int = 0
    analysed_chars: int = 0
    files_checked: int = 0
    files_skipped: int = 0
    duration_ms: int = 0

    inherited: int | None = None
    """How many findings this change worsened rather than introduced.

    Recorded from the day attribution shipped, deliberately ahead of anything
    that reads it. A trend can only be shown over history that was kept, so the
    cost of adding the field late is not the field — it is every turn recorded
    before it, which can never be classified afterwards.

    ``None`` for exactly those turns: written before this was recorded, so the
    split is unknown. Distinct from ``0``, which means the turn was classified
    and nothing was inherited. A trend that read the first as the second would
    invent a split for history that has none.
    """

    severities: tuple[str, ...] = ()
    """Status of each finding, so severity can be reported separately from count."""

    confidences: tuple[str, ...] = ()
    """How each finding was derived. Only ``exact`` may block, so the mix says
    how much of the output is authoritative rather than advisory."""

    languages: tuple[str, ...] = ()
    """Extensions of the files analysed — the honest view of what coverage this
    install actually has, given Python is the only exact analyser today."""

    checked: tuple[str, ...] = ()
    """Paths analysed, capped. Needed to tell a finding that was fixed from one
    in a file nothing has looked at since."""

    at: int = 0
    """When this was recorded, in whole seconds since the epoch. Stamped by
    ``record``, never by ``observe`` — the clock is a surface concern, and a
    check that reads one is not reproducible (RULES.md section 4). Zero on
    events written before the field existed."""

    run: str = ""
    """Groups every verdict from one orchestrated job. Set by the orchestrator
    through ``YIELDPOINT_RUN_ID``; empty when nobody is coordinating."""

    agent: str = ""
    """Which worker produced this verdict, from ``YIELDPOINT_AGENT``. With a
    fan-out of three hundred, "what did the suite look like" is far less useful
    than "which agent keeps weakening it"."""

    acknowledged: int = 0
    """Findings a source comment answered. Counted so suppression stays visible."""

    keys: tuple[str, ...] = ()
    """``file::rule`` per finding, so the same problem can be recognised across
    verdicts."""

    context: dict | None = None
    """Measured compaction metadata; no source content. None for verification."""

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_dict(cls, data: dict) -> "Event":
        """Read one row. Absent fields take their default, not an error."""
        event = cls(
            surface=str(data.get("surface", "")),
            status=str(data.get("status", "")),
            findings=int(data.get("findings", 0)),
            rules=tuple(data.get("rules", ())),
            prescription_chars=int(data.get("prescription_chars", 0)),
            analysed_chars=int(data.get("analysed_chars", 0)),
            files_checked=int(data.get("files_checked", 0)),
            files_skipped=int(data.get("files_skipped", 0)),
            duration_ms=int(data.get("duration_ms", 0)),
            at=int(data.get("at", 0)),
            run=str(data.get("run", "")),
            agent=str(data.get("agent", "")),
            acknowledged=int(data.get("acknowledged", 0)),
            # Absent in every row written before attribution shipped, and
            # left as None there: unknown is not zero.
            inherited=_split(data),
            severities=tuple(data.get("severities", ())),
            confidences=tuple(data.get("confidences", ())),
            languages=tuple(data.get("languages", ())),
            checked=tuple(data.get("checked", ())),
            keys=tuple(data.get("keys", ())),
            context=data.get("context"),
        )
        numeric = ("findings", "prescription_chars", "analysed_chars", "files_checked",
                   "files_skipped", "duration_ms", "at", "acknowledged")
        if any(type(data.get(key, 0)) is not int or data.get(key, 0) < 0 for key in numeric):
            raise ValueError("invalid event count")
        for key in ("rules", "severities", "confidences", "languages", "checked", "keys"):
            if not isinstance(data.get(key, ()), (list, tuple)) or not all(
                    isinstance(value, str) for value in data.get(key, ())):
                raise ValueError("invalid event list")
        if event.context is not None:
            from .contextstats import known
            if not known(event.context):
                raise ValueError("invalid context metrics")
        return event



def parse_events(text: str) -> list[Event]:
    """Skip damaged and incomplete records without changing valid counts."""
    events = []
    for line in text.splitlines(keepends=True):
        if not line.endswith("\n"):
            continue
        try:
            data = json.loads(line)
            if not isinstance(data, dict) or not data.get("surface") or not data.get("status"):
                continue
            events.append(Event.from_dict(data))
        except (ValueError, TypeError, OverflowError):
            continue
    return events
