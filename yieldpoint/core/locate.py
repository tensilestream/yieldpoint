"""Finding the repository a path belongs to.

Everything Yieldpoint writes — the ledger, the import graph, the analysis cache
— belongs in one place per repository. Without a shared answer to "which
repository is this?", each command stores its state wherever it happened to be
pointed, and a project ends up with several ``.yieldpoint`` directories holding
partial views of the same work.

The answer is deliberately the same one the policy uses: the nearest ancestor
holding ``.yieldpoint.json``, then the nearest holding ``.git``. A path with
neither is its own root, which is the right behaviour for a scratch directory
and for a test.
"""

from __future__ import annotations

from pathlib import Path

from .policy import CONFIG_FILENAME

MARKERS = (CONFIG_FILENAME, ".git")


def repository(start: str | Path = ".") -> Path:
    """The root of the repository containing ``start``.

    Never raises and never returns ``None``: a directory outside any project is
    its own root, so state is written somewhere predictable rather than nowhere.
    """
    try:
        current = Path(start).resolve()
    except OSError:
        return Path(start)

    if current.is_file():
        current = current.parent

    for marker in MARKERS:
        for directory in (current, *current.parents):
            if (directory / marker).exists():
                return directory
    return current


__all__ = ["repository", "MARKERS"]
