"""A content-addressed store for analysis results.

Measuring a module costs roughly four times what parsing it does, and most of
what any run measures is a file that has not changed since the last one. So the
result is kept, keyed by a hash of the source itself.

**Keyed by content, not by path.** A file that is renamed, or that appears at a
different path in a replayed commit, is the same input and gets the same answer.
This is also what makes the cache safe: the function being cached is pure, so a
hit is indistinguishable from a recomputation, and RULES.md section 4 still
holds — same input, same bytes out.

SQLite from the standard library, so the persistence costs no dependency. It
handles many agent processes writing at once, which a file full of JSON does
not.

**Where this does not help, and it is worth being plain about it.** Verifying a
change means comparing a before state with an after state. The before state is
on disk or in git and caches well. The after state is content the agent has just
composed: it has never existed, so nothing can have stored it. An index makes a
repository scan dramatically cheaper and an interactive edit only somewhat
cheaper, and no amount of indexing changes that.
"""

from __future__ import annotations

import atexit
import hashlib
import json
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

DEFAULT_PATH = ".yieldpoint/analysis.sqlite3"

#: Bumped whenever a cached payload's shape changes, so entries written by an
#: older build are ignored rather than misread.
CACHE_VERSION = 1

#: Rows kept. Beyond this the oldest are dropped — an accounting aid, not a
#: data store, and an unbounded file in someone's repository is a bug.
MAX_ROWS = 50_000

_LOCAL = threading.local()
_ALL: list = []
_ALL_LOCK = threading.Lock()
_MEMO: dict[str, Any] = {}
_MEMO_LIMIT = 2_000

#: Writes between pruning checks. Counting the table on every write makes each
#: one cost O(rows), which turned a cache that wins on every individual lookup
#: into one that made a whole-repository scan slower. Pruning is housekeeping;
#: it does not need to be exact.
_PRUNE_EVERY = 2_000
_WRITES = 0

_CONFIGURED: dict[str, Path] = {}


def configure(root: str | Path) -> None:  # noqa: D401 - see below
    """Point the cache at a repository rather than the working directory.

    Without this the store lands wherever the command happened to be run from,
    which means two projects share one cache and a scan populates the wrong
    directory. Keyed by content, so sharing is harmless in principle — but a
    cache nobody can find is a cache nobody benefits from.
    """
    if _CONFIGURED.get("root") != Path(root):
        close()  # the old connection points at a different repository
    _CONFIGURED["root"] = Path(root)


def _resolve(path: str | Path | None) -> Path:
    if path is not None:
        return Path(path)
    return _CONFIGURED.get("root", Path(".")) / DEFAULT_PATH


def key(source: str, kind: str) -> str:
    """The identity of one analysis: what was analysed, and by which routine."""
    digest = hashlib.blake2b(source.encode("utf-8", "replace"), digest_size=16)
    return f"{CACHE_VERSION}:{kind}:{digest.hexdigest()}"


@dataclass(frozen=True)
class Codec:
    """How one analysis turns into a row and back.

    Bundled rather than passed as three more arguments: this is the seam where
    a cached type is defined, and it reads better as one thing than as a
    signature nobody wants to look at.
    """

    kind: str
    encode: Callable[[Any], dict]
    decode: Callable[[dict], Any]


def through(source: str, codec: Codec, compute: Callable[[], Any],
            path: str | Path | None = None) -> Any:
    """Return the cached analysis, computing and storing it on a miss.

    Every failure mode here resolves to "compute it": a missing database, a
    locked one, a payload this build cannot read. The cache can make things
    slow; it is not permitted to make them wrong.
    """
    identity = key(source, codec.kind)
    if identity in _MEMO:
        return _MEMO[identity]

    stored = _read(identity, path)
    if stored is not None:
        try:
            value = codec.decode(stored)
            _remember(identity, value)
            return value
        except (KeyError, TypeError, ValueError):
            pass  # written by a build that disagreed; recompute

    value = compute()
    _remember(identity, value)
    try:
        _write(identity, codec.encode(value), path)
    except (TypeError, ValueError, sqlite3.Error):
        pass
    return value


def _remember(identity: str, value: Any) -> None:
    if len(_MEMO) >= _MEMO_LIMIT:
        _MEMO.clear()  # simplest bound that cannot leak; a scan refills it
    _MEMO[identity] = value


def _connect(path: str | Path | None) -> sqlite3.Connection | None:
    """One connection per thread. None when the database cannot be opened."""
    target = _resolve(path)
    cached = getattr(_LOCAL, "connections", None)
    if cached is None:
        cached = _LOCAL.connections = {}
    if str(target) in cached:
        return cached[str(target)]

    connection = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        marker = target.parent / ".gitignore"
        if not marker.exists():
            marker.write_text("*\n", encoding="utf-8")
        connection = sqlite3.connect(str(target), timeout=5.0, isolation_level=None)
        # WAL lets readers and a writer coexist, which is the whole point when
        # several agents are verifying against one repository at once.
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        # No explicit sequence column: SQLite's own rowid already increases
        # with insertion order, and asking for MAX(seq) on every write was half
        # the reason writing was slow.
        connection.execute(
            "CREATE TABLE IF NOT EXISTS analysis ("
            "  id TEXT PRIMARY KEY,"
            "  payload TEXT NOT NULL"
            ")"
        )
    except (OSError, sqlite3.Error):
        if connection is not None:
            try:
                connection.close()
            except sqlite3.Error:
                pass
        cached[str(target)] = None
        return None

    cached[str(target)] = connection
    with _ALL_LOCK:
        _ALL.append(connection)
    return connection


def _read(identity: str, path) -> dict | None:
    connection = _connect(path)
    if connection is None:
        return None
    try:
        row = connection.execute(
            "SELECT payload FROM analysis WHERE id = ?", (identity,)
        ).fetchone()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    try:
        payload = json.loads(row[0])
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def _write(identity: str, payload: dict, path) -> None:
    connection = _connect(path)
    if connection is None:
        return
    global _WRITES
    try:
        connection.execute(
            "INSERT OR REPLACE INTO analysis (id, payload) VALUES (?, ?)",
            (identity, json.dumps(payload, separators=(",", ":"))),
        )
        _WRITES += 1
        if _WRITES % _PRUNE_EVERY == 0:
            _prune(connection)
    except sqlite3.Error:
        return


def _prune(connection: sqlite3.Connection) -> None:
    """Drop the oldest rows. Occasional by design — see _PRUNE_EVERY."""
    row = connection.execute("SELECT COUNT(*) FROM analysis").fetchone()
    if not row or row[0] <= MAX_ROWS:
        return
    connection.execute(
        "DELETE FROM analysis WHERE rowid IN ("
        "  SELECT rowid FROM analysis ORDER BY rowid LIMIT ?"
        ")",
        (row[0] - MAX_ROWS,),
    )


def close() -> None:
    """Close this thread's connections. Registered at exit, and used by tests.

    Left open they are reclaimed at interpreter shutdown with a warning, which
    is noise that trains people to ignore warnings.
    """
    with _ALL_LOCK:
        connections, _ALL[:] = list(_ALL), []
    for connection in connections:
        try:
            connection.close()
        except sqlite3.Error:
            pass
    cached = getattr(_LOCAL, "connections", None)
    if cached is not None:
        cached.clear()


def clear() -> None:
    """Drop the in-process memo. For tests, and after changing an analyser."""
    _MEMO.clear()


atexit.register(close)

__all__ = [
    "Codec", "through", "key", "clear", "close", "configure",
    "DEFAULT_PATH", "CACHE_VERSION", "MAX_ROWS",
]
