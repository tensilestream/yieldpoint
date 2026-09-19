"""Handing new events to a command the user chose.

Exporting metrics to a collector is a real need — a value claim nobody can
aggregate is barely better than one nobody can check. Satisfying it with an HTTP
client in this package would retire the guarantee that Yieldpoint makes no
network call, which is stated in the README, in RULES.md section 4, in
SECURITY.md, and enforced by this repository's own boundary rule.

So the network belongs to the caller: ``YIELDPOINT_SINK`` names a command as
argv, this module spawns it, and writes JSON Lines to its stdin. Yieldpoint
never opens a socket, the guarantee survives word for word, and the command can
be curl, a log file, or anything that reads stdin.

**It is read from the environment and never from ``.yieldpoint.json``.** That
file is committed, and SECURITY.md states that configuration must never be able
to name an executable — a repository that could would run a command on every
machine that cloned it and ran one turn. The environment belongs to the person
at the keyboard; the repository belongs to whoever opened the last pull request.
JSON array rather than a shell string, so nothing is word-split or expanded.

A watermark records the timestamp of the last event handed over, so a turn
exports only what is new. It is advisory: losing it re-sends, which a collector
keyed on ``at`` can drop, and that is the right way round — re-sending is a
duplicate, while skipping is a hole.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

#: Never let an export hang a turn. The ledger is bookkeeping; the verdict is
#: the product, and no accounting step may delay one.
TIMEOUT_SECONDS = 10


def watermark_path(ledger_path: Path) -> Path:
    return ledger_path.with_name(ledger_path.name + ".sent")


def _last_sent(path: Path) -> int:
    try:
        return int(path.read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        return 0


def _remember(path: Path, at: int) -> None:
    try:
        path.write_text(str(at), encoding="utf-8")
    except OSError:
        pass  # a lost watermark re-sends; it never skips


def pending(events, ledger_path: Path) -> list:
    """Events newer than the watermark, oldest first."""
    since = _last_sent(watermark_path(ledger_path))
    return sorted((e for e in events if e.at > since), key=lambda e: e.at)


#: The one place a sink may come from. Deliberately not the committed policy.
ENV_VAR = "YIELDPOINT_SINK"


def configured() -> tuple[str, ...]:
    """The sink command as argv, from the environment. Empty when unset or bad.

    A malformed value is ignored rather than raised: an export is bookkeeping,
    and a typo in an environment variable must not stop a verification.
    """
    raw = os.environ.get(ENV_VAR, "").strip()
    if not raw:
        return ()
    try:
        parsed = json.loads(raw)
    except ValueError:
        return ()
    if not isinstance(parsed, list) or not parsed:
        return ()
    if not all(isinstance(part, str) for part in parsed):
        return ()
    return tuple(parsed)


def flush(policy, events, ledger_path: Path) -> int:
    """Hand new events to the configured command. Returns how many were sent.

    Never raises. An export that fails must not fail the turn that produced the
    data, so every error here is swallowed and reported as zero.
    """
    del policy  # the sink is environment-only, by SECURITY.md
    argv = configured()
    if not argv:
        return 0
    fresh = pending(events, ledger_path)
    if not fresh:
        return 0

    from .timeline import timeline

    payload = "".join(
        json.dumps(turn.to_dict(), separators=(",", ":")) + "\n"
        for turn in timeline(fresh)
    )
    try:
        subprocess.run(
            list(argv),
            input=payload.encode("utf-8"),
            timeout=TIMEOUT_SECONDS,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return 0  # the watermark is deliberately not advanced; it retries
    _remember(watermark_path(ledger_path), fresh[-1].at)
    return len(fresh)


__all__ = ["flush", "configured", "pending", "watermark_path",
           "ENV_VAR", "TIMEOUT_SECONDS"]
