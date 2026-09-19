"""What Yieldpoint actually did, recorded so the value can be checked.

The product claims a deterministic critique that costs no model calls. That is
true by construction, and completely invisible — which makes it indistinguishable
from a claim. This module is the evidence: every verdict appends one line to a
local file, and ``yieldpoint stats`` adds them up.

**Three kinds of number, never blended.** Mixing them is how tools end up quoting
savings nobody can reproduce, which RULES.md section 5 exists to prevent:

*Measured* — counted from what happened. Verdicts run, findings by rule,
prescription characters, source characters analysed, elapsed milliseconds.

*Architectural* — true by construction, not by observation. Yieldpoint makes zero
model calls, so an LLM-as-judge doing the same job costs one call per verdict.
That is a property of how each is built and needs no benchmark.

*Estimated* — arithmetic on measured bytes with the assumption printed next to
the result. Token counts are characters divided by a stated constant, because
the real number depends on a tokenizer this package will not take a dependency
on. Labelled as an estimate everywhere it appears.

**Local only.** Nothing is transmitted anywhere; there is no network call in this
package at all. The file is plain JSON Lines, is deleted by removing it, and
recording is switched off with ``"metrics": {"enabled": false}``.

**Outside the verification path.** Recording happens after a verdict exists and
can never change one. The clock is read here and nowhere in ``core`` — RULES.md
section 4 forbids that, and a timed check is not a reproducible check.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

DEFAULT_PATH = ".yieldpoint/metrics.jsonl"

#: Characters per token. A deliberate, stated approximation: real tokenizers
#: disagree with each other and pinning one would mean a dependency and a lie
#: about precision. Every figure derived from it is labelled an estimate.
CHARS_PER_TOKEN = 4

#: Cap on one serialised event, in bytes. This is a **correctness** limit, not
#: tidiness. A POSIX ``O_APPEND`` write is atomic only up to the pipe buffer, so
#: a line over that can interleave with another process's line and corrupt both.
#: Three hundred agents appending concurrently is exactly when that happens, so
#: the variable-length fields are trimmed until the line fits.
MAX_LINE_BYTES = 3_500

#: Rotate once the file passes this. The ledger is an accounting aid, not a data
#: store, and an unbounded file in someone's repository is a bug.
MAX_BYTES = 8_000_000


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

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_dict(cls, data: dict) -> "Event":
        return cls(
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
            severities=tuple(data.get("severities", ())),
            confidences=tuple(data.get("confidences", ())),
            languages=tuple(data.get("languages", ())),
            checked=tuple(data.get("checked", ())),
            keys=tuple(data.get("keys", ())),
        )


#: Paths recorded per event. Bounded so one scan of a large repository cannot
#: write a line long enough to matter.
MAX_PATHS = 60


@dataclass(frozen=True)
class Who:
    """Which orchestrated run and which worker produced a verdict.

    Field order is part of the contract: ``identity()`` returns ``(run, agent)``
    and is splatted into this. Inserting a field above them silently rebinds
    both, which is a bug no type checker catches and no verdict looks wrong
    from — the attribution is simply wrong afterwards.
    """

    run: str = ""
    agent: str = ""


def identity() -> tuple[str, str]:
    """``(run, agent)`` for this process, from the environment.

    Read here rather than in ``core`` — this is a surface concern, and RULES.md
    section 4 keeps environment reads out of the verification path. An
    orchestrator fanning out sets these once per worker; a lone developer sets
    neither and the fields stay empty.
    """
    return (
        os.environ.get("YIELDPOINT_RUN_ID", "")[:64],
        os.environ.get("YIELDPOINT_AGENT", "")[:64],
    )


def observe(verdict, surface: str, *, analysed_chars: int = 0,
            duration_ms: int = 0, who: "Who | None" = None) -> Event:
    """Build the event for a verdict. Pure: no clock, no filesystem.

    ``who`` defaults to the environment, which is how a fan-out labels three
    hundred workers without threading an identifier through every call site.
    """
    findings = verdict.findings
    origin = who or Who(*identity())
    return Event(
        run=origin.run,
        agent=origin.agent,
        surface=surface,
        status=verdict.status.value,
        findings=len(findings),
        rules=tuple(sorted({f.rule for f in findings})),
        prescription_chars=len(verdict.prescription or ""),
        analysed_chars=analysed_chars,
        files_checked=len(verdict.checked),
        files_skipped=len(verdict.skipped),
        duration_ms=duration_ms,
        acknowledged=len(getattr(verdict, "acknowledged", ())),
        severities=tuple(sorted(f.status.value for f in findings)),
        confidences=tuple(sorted(f.confidence.value for f in findings)),
        languages=tuple(sorted({_language(path) for path in verdict.checked})),
        checked=tuple(sorted(verdict.checked))[:MAX_PATHS],
        keys=tuple(sorted({f"{f.file}::{f.rule}" for f in findings}))[:MAX_PATHS],
    )


def _language(path: str) -> str:
    """The extension, or ``other``. Not a language detector — a grouping key."""
    _, _, suffix = path.rpartition(".")
    return suffix.lower() if suffix and suffix != path else "other"


def stamp(event: Event) -> Event:
    """Add the wall-clock time. Separated so ``observe`` stays pure."""
    return event if event.at else replace(event, at=int(time.time()))


def record(event: Event, path: str | Path = DEFAULT_PATH) -> bool:
    """Append one event, stamped with the time. Never raises.

    A failure to record must never fail a verification — the verdict is the
    product and the ledger is bookkeeping, so every error here is swallowed.
    """
    try:
        target = Path(path)
        _prepare(target.parent)
        line = _fit(stamp(event))
        # One atomic append. No read-modify-write anywhere in this path: with
        # many agents writing at once, reading the file in order to rewrite it
        # is how lines get lost.
        with target.open("a", encoding="utf-8") as handle:
            handle.write(line)
        _rotate(target)
        return True
    except (OSError, TypeError, ValueError):
        return False


def _fit(event: Event) -> str:
    """Serialise, trimming the variable-length fields until the line is atomic.

    ``checked`` and ``keys`` are the only fields that grow with the size of the
    change, so they are what gets shortened. Counts are never touched: a
    shorter list is a smaller sample, a wrong count is a wrong number.
    """
    line = event.to_json()
    while len(line.encode("utf-8")) > MAX_LINE_BYTES and (event.checked or event.keys):
        event = replace(
            event,
            checked=event.checked[: max(0, len(event.checked) // 2)],
            keys=event.keys[: max(0, len(event.keys) // 2)],
        )
        line = event.to_json()
    return line + "\n"


def _prepare(directory: Path) -> None:
    """Create the directory, and make it ignore itself.

    A self-ignoring directory means nobody has to remember to add a line to
    ``.gitignore``, and Yieldpoint never edits a file the project owns. The
    ledger is local bookkeeping; committing it would be noise in every diff.
    """
    directory.mkdir(parents=True, exist_ok=True)
    marker = directory / ".gitignore"
    if not marker.exists():
        marker.write_text("*\n", encoding="utf-8")


def _rotate(target: Path) -> None:
    """Move the file aside once it is large, keeping one previous generation.

    Rotation is a single ``os.replace``, which is atomic, and only the process
    that wins an exclusive lock file attempts it. Rewriting the file in place —
    read the lines, drop the old ones, write it back — would silently discard
    whatever other agents appended in between.
    """
    try:
        if target.stat().st_size < MAX_BYTES:
            return
    except OSError:
        return

    guard = target.with_suffix(target.suffix + ".rotating")
    try:
        handle = os.open(str(guard), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError:
        return  # another process is rotating; appending meanwhile is safe
    try:
        os.close(handle)
        if target.stat().st_size >= MAX_BYTES:
            os.replace(str(target), str(target) + ".1")
    except OSError:
        pass
    finally:
        try:
            os.unlink(str(guard))
        except OSError:
            pass


def load(path: str | Path = DEFAULT_PATH) -> list[Event]:
    """Every recorded event, including the rotated generation.

    A missing or damaged file reads as no events. A partial line — which an
    append cannot produce, but a full disk can — is skipped without losing the
    rest of the file.
    """
    target = Path(path)
    text = _read(Path(str(target) + ".1")) + _read(target)
    events = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue  # a truncated write must not lose the rest of the file
        if isinstance(data, dict):
            events.append(Event.from_dict(data))
    return events


def _read(path: Path) -> str:
    """File contents, or empty when it is absent or unreadable."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


# Re-exported at the foot of the module so the rest of the package keeps one
# import. recording.py imports from here, so this has to come after everything
# it needs — the split is about which file a maintainer opens, not about
# giving callers two doors.
from .recording import (  # noqa: E402
    Run, Timer, enabled, path_for, record_run, under_test,
)

__all__ = [
    "Event", "Who", "observe", "record", "stamp", "load",
    "Run", "Timer", "record_run", "enabled", "under_test", "path_for",
    "DEFAULT_PATH", "CHARS_PER_TOKEN", "MAX_LINE_BYTES", "MAX_BYTES",
]
