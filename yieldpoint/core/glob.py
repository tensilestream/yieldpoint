"""Bounded glob matching.

Deliberately minimal: ``**`` crosses separators, ``*`` stays within a segment,
``?`` is one character. No brace expansion, no extglob, no backtracking traps —
a policy pattern must always terminate, and must mean the same thing on every
host, so paths are normalised to POSIX form before comparison.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Iterable


def normalize(path: str) -> str:
    """Normalise to forward slashes with no duplicate or leading-``./`` noise.

    ``src/a.py``, ``.\\src\\a.py`` and ``src//a.py`` all compare equal.
    """
    text = str(path).replace("\\", "/")
    text = re.sub(r"/{2,}", "/", text)
    if text.startswith("./"):
        text = text[2:]
    return text


@lru_cache(maxsize=512)
def compile_pattern(pattern: str) -> re.Pattern[str]:
    """Translate one glob into an anchored regex. Cached; patterns are few."""
    glob = normalize(pattern)
    out: list[str] = []
    i = 0
    while i < len(glob):
        char = glob[i]
        if char == "*":
            if glob[i + 1 : i + 2] == "*":
                # "**/" also matches zero segments, so "src/**/a.py" matches "src/a.py".
                if glob[i + 2 : i + 3] == "/":
                    out.append("(?:.*/)?")
                    i += 3
                    continue
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(char))
        i += 1
    return re.compile("^" + "".join(out) + "$")


def matches(pattern: str, path: str) -> bool:
    return compile_pattern(pattern).search(normalize(path)) is not None


def matches_any(patterns: Iterable[str], path: str) -> bool:
    target = normalize(path)
    return any(compile_pattern(p).search(target) is not None for p in patterns)


def first_match(patterns: Iterable[str], path: str) -> str | None:
    """The first matching pattern, for reporting *which* rule fired."""
    target = normalize(path)
    for pattern in patterns:
        if compile_pattern(pattern).search(target) is not None:
            return pattern
    return None
