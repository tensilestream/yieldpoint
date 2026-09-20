"""The same implementation in two different files.

``structure._duplicates`` compares functions inside one file, which is the
easy half. The copy that actually hurts is the one in another module: nobody
reading either file can see the other, so the two drift, and a fix applied to
one is a bug left in the other.

Shape, not text. A copy-paste that renamed its variables is still found, and
two short accessors that happen to match are not — coincidence at three lines
is common enough that reporting it would train people to ignore the rule.
"""

from __future__ import annotations

from .metrics import measure
from .verdict import Confidence, Finding, Status

DUPLICATE_ACROSS_FILES = "duplicate_across_files"


def _shapes(source: str, path: str) -> dict[str, object]:
    """Substantial functions in one file, keyed by structural shape."""
    module = measure(source, filename=path)
    if not module.ok:
        return {}
    return {f.shape: f for f in module.functions if f.substantial}


def check(states, severity: Status | None) -> list[Finding]:
    """Functions duplicated between two files of one change set.

    ``states`` is ``(path, before, after)`` per changed file, as verify_diff
    holds them. Only the after-state matters: what the change leaves behind.
    """
    if severity is None:
        return []

    seen: dict[str, tuple[str, object]] = {}
    findings: list[Finding] = []

    for path, _before, after in sorted(states, key=lambda s: s[0]):
        if after is None or not path.endswith(".py"):
            continue
        for shape, function in sorted(_shapes(after, path).items()):
            if shape not in seen:
                seen[shape] = (path, function)
                continue
            origin_path, origin = seen[shape]
            if origin_path == path:
                continue          # structure.py owns the within-file case
            findings.append(Finding(
                rule=DUPLICATE_ACROSS_FILES,
                status=severity,
                file=path,
                line=function.line,
                detail=(f"`{function.qualname}` is structurally identical to "
                        f"`{origin.qualname}` in {origin_path}."),
                prescription=(
                    "Extract the shared implementation into one module and call "
                    "it from both. Two copies in different files drift apart "
                    "without either reader noticing."
                ),
                symbol=function.qualname,
                confidence=Confidence.EXACT,
            ))
    return findings


__all__ = ["check", "DUPLICATE_ACROSS_FILES"]
