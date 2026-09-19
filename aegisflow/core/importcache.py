"""Building the import graph once, not once per change.

Reading every file to find its imports costs about eight seconds on a
twelve-thousand module repository. That is fine once and unacceptable per
verdict, and catastrophic when forty workers each do it on startup.

So the graph is cached beside the ledger, keyed by a **fingerprint** of the
tree: how many source files there are, their total size, and the newest
modification time. Cheap to compute — it stats files without reading them — and
it changes whenever anything a graph depends on changes.

The cache is distrusted on read. A missing, corrupt, or stale entry costs one
rebuild rather than a wrong answer, which is the only acceptable trade for
something that feeds a safety decision.

Concurrency is handled by writing to a temporary file and renaming it, which is
atomic. Two workers racing both build and both write; the loser's work is
wasted and the result is identical, because the graph is a pure function of the
tree.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

from .importgraph import EXACT_SUFFIXES, LEXICAL_SUFFIXES, Graph, build

DEFAULT_CACHE = ".aegisflow/importgraph.json"

#: Bumped when the graph's shape changes, so an old cache is ignored rather
#: than misread.
CACHE_VERSION = 1


def fingerprint(root: str | Path) -> str:
    """A cheap summary of the tree, without reading any file's contents."""
    base = Path(root)
    count = 0
    total = 0
    newest = 0.0
    suffixes = EXACT_SUFFIXES + LEXICAL_SUFFIXES
    for path in base.rglob("*"):
        if not path.name.endswith(suffixes):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        count += 1
        total += stat.st_size
        newest = max(newest, stat.st_mtime)
    return f"{CACHE_VERSION}:{count}:{total}:{newest:.0f}"


def load_or_build(root: str | Path, cache: str | Path | None = None) -> Graph:
    """The graph for ``root``, from cache when the tree has not changed."""
    from .locate import repository

    base = Path(root)
    target = Path(cache) if cache else repository(base) / DEFAULT_CACHE
    mark = fingerprint(base)

    cached = _read(target, mark)
    if cached is not None:
        return cached

    graph = build(base)
    _write(target, mark, graph)
    return graph


def _read(target: Path, mark: str) -> Graph | None:
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("fingerprint") != mark:
        return None
    try:
        return Graph(
            fan_in=dict(data["fan_in"]),
            fan_out=dict(data["fan_out"]),
            modules=tuple(data["modules"]),
            exact=bool(data["exact"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _write(target: Path, mark: str, graph: Graph) -> None:
    """Best effort. Failing to cache is slow, never wrong."""
    temp = target.with_suffix(f".{os.getpid()}.tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        marker = target.parent / ".gitignore"
        if not marker.exists():
            marker.write_text("*\n", encoding="utf-8")
        temp.write_text(
            json.dumps({"fingerprint": mark, **asdict(graph)}), encoding="utf-8"
        )
        os.replace(str(temp), str(target))
    except OSError:
        try:
            temp.unlink()
        except OSError:
            pass


_MEMO: dict[str, Graph] = {}


def cached(root: str | Path = ".", *, refresh: bool = False) -> Graph:
    """The graph for ``root``, held for the life of this process.

    Even the cached path stats every file to check the fingerprint, which is
    most of a second on a large repository — fine once, not fine per verdict.
    So it is held in memory too.

    **This makes the graph a snapshot.** A long-running agent that adds an
    import will not see it reflected until something calls with
    ``refresh=True``. That is deliberate: importance here is a *ranking* of
    modules, and a ranking does not meaningfully change because one file gained
    one import. Correctness of a verdict never depends on it — only how much
    model a change is routed to.
    """
    key = str(Path(root).resolve())
    if refresh or key not in _MEMO:
        _MEMO[key] = load_or_build(root)
    return _MEMO[key]


def forget(root: str | Path | None = None) -> None:
    """Drop the in-memory snapshot. Used by tests, and after a large refactor."""
    if root is None:
        _MEMO.clear()
    else:
        _MEMO.pop(str(Path(root).resolve()), None)


__all__ = [
    "load_or_build", "cached", "forget", "fingerprint",
    "DEFAULT_CACHE", "CACHE_VERSION",
]
