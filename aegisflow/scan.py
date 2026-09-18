"""Auditing a repository as it stands.

Every other surface verifies a *change*: what did this edit do to what was there
before. This one answers a different question — what is the state of this
repository right now — which is what someone asks first, before any agent has
touched it.

The distinction matters because most rules are differential by design, so that
adopting AegisFlow does not blame inherited debt on the next edit. A scan has no
"before", so every rule runs in absolute mode and reports everything it finds.
A finding here is therefore a statement about the repository, not about anyone's
change, and the two must not be confused.

Assertion monotonicity cannot participate: it compares two states, and a scan
has one.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterator

from .core import glob
from .core.policy import Policy
from .core.verdict import Verdict
from .verify import EXACT_SUFFIXES, verify_change


@dataclass(frozen=True)
class ScanResult:
    verdict: Verdict
    files: int = 0
    unreadable: tuple[str, ...] = ()

    def by_rule(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for finding in self.verdict.findings:
            counts[finding.rule] = counts.get(finding.rule, 0) + 1
        return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def scan(root: str | Path = ".", policy: Policy | str | dict | None = None) -> ScanResult:
    """Audit every source file under ``root``.

    Structure limits are evaluated absolutely rather than differentially, because
    there is no previous state to have worsened.
    """
    resolved = Policy.load(policy)
    absolute = replace(resolved, structure=replace(resolved.structure, greenfield=True))
    base = Path(root)

    verdict = Verdict.of([])
    files = 0
    unreadable: list[str] = []

    for path in walk(base, absolute):
        relative = str(path.relative_to(base)) if path.is_relative_to(base) else str(path)
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            unreadable.append(f"{relative}: {exc}")
            continue
        files += 1
        verdict = verdict.merge(verify_change(None, source, relative, absolute))

    return ScanResult(verdict=verdict, files=files, unreadable=tuple(unreadable))


def walk(root: Path, policy: Policy) -> Iterator[Path]:
    """Yield analysable files under ``root``, in a stable order.

    Sorted rather than in filesystem order, so two scans of the same tree produce
    byte-identical output (RULES.md section 4).
    """
    if root.is_file():
        yield root
        return
    for path in sorted(root.rglob("*")):
        if not path.is_file() or not path.name.endswith(EXACT_SUFFIXES):
            continue
        relative = str(path.relative_to(root))
        if glob.matches_any(policy.scan.ignore, relative):
            continue
        try:
            if path.stat().st_size > policy.scan.max_file_bytes:
                continue
        except OSError:
            continue
        yield path
