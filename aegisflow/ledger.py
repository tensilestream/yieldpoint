"""What AegisFlow actually did, recorded so the value can be checked.

The product claims a deterministic critique that costs no model calls. That is
true by construction, and completely invisible — which makes it indistinguishable
from a claim. This module is the evidence: every verdict appends one line to a
local file, and ``aegisflow stats`` adds them up.

**Three kinds of number, never blended.** Mixing them is how tools end up quoting
savings nobody can reproduce, which RULES.md section 5 exists to prevent:

*Measured* — counted from what happened. Verdicts run, findings by rule,
prescription characters, source characters analysed, elapsed milliseconds.

*Architectural* — true by construction, not by observation. AegisFlow makes zero
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
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_PATH = ".aegisflow/metrics.jsonl"

#: Characters per token. A deliberate, stated approximation: real tokenizers
#: disagree with each other and pinning one would mean a dependency and a lie
#: about precision. Every figure derived from it is labelled an estimate.
CHARS_PER_TOKEN = 4

#: Cap on the recorded file, in lines. The ledger is an accounting aid, not a
#: data store, and an unbounded file in someone's repository is a bug.
MAX_LINES = 20_000


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
        )


def observe(verdict, surface: str, *, analysed_chars: int = 0,
            duration_ms: int = 0) -> Event:
    """Build the event for a verdict. Pure: no clock, no filesystem."""
    return Event(
        surface=surface,
        status=verdict.status.value,
        findings=len(verdict.findings),
        rules=tuple(sorted({f.rule for f in verdict.findings})),
        prescription_chars=len(verdict.prescription or ""),
        analysed_chars=analysed_chars,
        files_checked=len(verdict.checked),
        files_skipped=len(verdict.skipped),
        duration_ms=duration_ms,
    )


def record(event: Event, path: str | Path = DEFAULT_PATH) -> bool:
    """Append one event. Returns whether it was written; never raises.

    A failure to record must never fail a verification — the verdict is the
    product and the ledger is bookkeeping, so every error here is swallowed.
    """
    try:
        target = Path(path)
        _prepare(target.parent)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(event.to_json() + "\n")
        _trim(target)
        return True
    except (OSError, TypeError, ValueError):
        return False


def _prepare(directory: Path) -> None:
    """Create the directory, and make it ignore itself.

    A self-ignoring directory means nobody has to remember to add a line to
    ``.gitignore``, and AegisFlow never edits a file the project owns. The
    ledger is local bookkeeping; committing it would be noise in every diff.
    """
    directory.mkdir(parents=True, exist_ok=True)
    marker = directory / ".gitignore"
    if not marker.exists():
        marker.write_text("*\n", encoding="utf-8")


def _trim(target: Path) -> None:
    """Keep the file bounded, dropping the oldest lines."""
    try:
        if target.stat().st_size < MAX_LINES * 120:
            return  # cheap guard: only read the file when it could be too long
        lines = target.read_text(encoding="utf-8").splitlines()
        if len(lines) <= MAX_LINES:
            return
        target.write_text("\n".join(lines[-MAX_LINES:]) + "\n", encoding="utf-8")
    except OSError:
        return


def load(path: str | Path = DEFAULT_PATH) -> list[Event]:
    """Every recorded event. A missing or damaged file reads as no events."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
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


class Timer:
    """Elapsed milliseconds around a verification, read outside ``core``."""

    def __init__(self) -> None:
        self._start = 0.0
        self.elapsed_ms = 0

    def __enter__(self) -> "Timer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc) -> bool:
        self.elapsed_ms = int((time.perf_counter() - self._start) * 1000)
        return False


def enabled(policy) -> bool:
    """Whether to record, honouring the policy and an environment override.

    ``AEGISFLOW_NO_METRICS`` switches it off without editing a committed file,
    which is what a CI job or a privacy-conscious user reaches for first.
    """
    if os.environ.get("AEGISFLOW_NO_METRICS"):
        return False
    return bool(getattr(getattr(policy, "metrics", None), "enabled", True))


def path_for(policy, root: str | Path = ".") -> Path:
    configured = getattr(getattr(policy, "metrics", None), "path", None)
    return Path(root) / (configured or DEFAULT_PATH)


__all__ = [
    "Event", "Timer", "observe", "record", "load", "enabled", "path_for",
    "DEFAULT_PATH", "CHARS_PER_TOKEN", "MAX_LINES",
]
