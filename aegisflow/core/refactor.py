"""Refactor integrity.

Test tampering and refactor breakage are different failures. Tampering weakens
what is verified; a broken refactor leaves code that still parses and no longer
resolves — a definition moved or renamed, a call site left behind.

Both rules here are **differential**: a name already dangling before the change
is not this change's fault, and neither is an export that was already gone.
Adopting AegisFlow on an existing repository must not produce a wall of findings
nobody caused.

Applies to every Python file, not only protected tests — refactors happen in
source, which is precisely where the verifier was previously silent.
"""

from __future__ import annotations

from typing import Iterable

from .symbols import Symbols, scan
from .verdict import Confidence, Finding, Status

DANGLING_REFERENCE = "dangling_reference"
EXPORT_REMOVED = "export_removed"


def check(
    before: str | None,
    after: str | None,
    path: str,
    *,
    on_dangling: Status | None = Status.REPAIR,
    on_export_removed: Status | None = Status.REPAIR,
    also_defined: Iterable[str] = (),
) -> tuple[list[Finding], list[str]]:
    """Compare the name structure of one file across a change."""
    if after is None:
        return [], []

    after_symbols = scan(after or "", filename=path)
    if not after_symbols.ok:
        return [], [f"{path}: {after_symbols.error}"]

    before_symbols = scan(before or "", filename=path)
    if before is not None and not before_symbols.ok:
        return [], [f"{path}: before state — {before_symbols.error}"]

    findings: list[Finding] = []
    skipped: list[str] = []

    if after_symbols.star_import:
        skipped.append(f"{path}: uses `import *`, so name resolution is not decidable")
    elif on_dangling is not None:
        findings.extend(_dangling(before_symbols, after_symbols, path, on_dangling))

    if on_export_removed is not None:
        findings.extend(
            _exports(before_symbols, after_symbols, path, on_export_removed, set(also_defined))
        )
    return findings, skipped


def _dangling(
    before: Symbols, after: Symbols, path: str, status: Status
) -> list[Finding]:
    """Names the change left pointing at nothing."""
    existing = set(before.dangling()) if before.ok else set()
    return [
        Finding(
            rule=DANGLING_REFERENCE,
            status=status,
            file=path,
            line=after.lines.get(name, 1),
            detail=f"`{name}` is used here but nothing in this module defines or imports it.",
            prescription=(
                f"Import `{name}` from wherever it now lives, restore its definition, or "
                f"update the reference to the name it was renamed to. A refactor that moves "
                f"a definition must move or update every use of it."
            ),
            symbol=name,
            confidence=Confidence.EXACT,
        )
        for name in after.dangling()
        if name not in existing
    ]


def _exports(
    before: Symbols, after: Symbols, path: str, status: Status, also_defined: set[str]
) -> list[Finding]:
    """Names dropped from ``__all__`` and defined nowhere in the change set."""
    if not before.exports:
        return []
    surviving = set(after.exports) | set(after.definitions) | also_defined
    return [
        Finding(
            rule=EXPORT_REMOVED,
            status=status,
            file=path,
            line=1,
            detail=f"`{name}` was part of this module's public API and is now gone.",
            prescription=(
                f"Restore `{name}`, or re-export it from wherever it moved. If removing it "
                f"is intended, say so explicitly — callers outside this change set still "
                f"import it."
            ),
            symbol=name,
            confidence=Confidence.EXACT,
        )
        for name in sorted(set(before.exports) - surviving)
    ]
