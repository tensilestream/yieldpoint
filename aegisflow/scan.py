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

import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Iterator

from .core import glob
from .core.policy import Policy
from .core.verdict import Verdict
from .verify import EXACT_SUFFIXES, verify_change

Progress = Callable[[int, int, str], None]
"""Called as ``(done, total, path)`` while a scan runs. For display only — it
must never influence a verdict, or the same tree would audit differently
depending on whether anyone was watching."""

#: Below this many files, a process pool costs more than it saves: interpreter
#: startup and pickling a policy per worker is measured in hundreds of
#: milliseconds, which is most of a small scan.
PARALLEL_THRESHOLD = 300


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


def scan(
    root: str | Path = ".",
    policy: Policy | str | dict | None = None,
    *,
    jobs: int | None = None,
    progress: Progress | None = None,
) -> ScanResult:
    """Audit every source file under ``root``.

    Structure limits are evaluated absolutely rather than differentially, because
    there is no previous state to have worsened.

    ``jobs`` spreads the work over processes; ``None`` picks a sensible number
    and falls back to one for a small tree. **The result does not depend on it.**
    Each file is verified independently and the findings are sorted by a stable
    key, so one worker and sixteen produce byte-identical output — which is the
    only reason parallelism is allowed here at all (RULES.md section 4).
    """
    resolved = Policy.load(policy)
    absolute = replace(resolved, structure=replace(resolved.structure, greenfield=True))
    base = Path(root)
    paths = list(walk(base, absolute))

    workers = _workers(jobs, len(paths))
    outcomes = (
        _serial(paths, base, absolute, progress) if workers == 1
        else _parallel(paths, base, absolute, workers, progress)
    )

    verdicts: list[Verdict] = []
    files = 0
    unreadable: list[str] = []
    for relative, result in outcomes:
        if isinstance(result, str):
            unreadable.append(f"{relative}: {result}")
            continue
        files += 1
        verdicts.append(result)

    # Combined once rather than folded with merge: see Verdict.combine.
    return ScanResult(
        verdict=Verdict.combine(verdicts), files=files, unreadable=tuple(unreadable)
    )


def _workers(jobs: int | None, total: int) -> int:
    if jobs is not None:
        return max(1, jobs)
    if total < PARALLEL_THRESHOLD:
        return 1
    return max(1, min(os.cpu_count() or 1, 16))


def _relative(path: Path, base: Path) -> str:
    return str(path.relative_to(base)) if path.is_relative_to(base) else str(path)


def verify_one(path: Path, base: Path, policy: Policy):
    """Audit one file. Returns a Verdict, or the reason it could not be read."""
    relative = _relative(path, base)
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return relative, str(exc)
    return relative, verify_change(None, source, relative, policy)


def verify_chunk(task):
    """Audit a batch of files in one worker. What the process pool calls.

    Batched rather than one task per file: the policy and the root have to be
    pickled into the worker with every task, and at one task per file that
    marshalling costs more than the analysis. Measured at 2,000 files, batching
    is the difference between a 1.3x speed-up and a useful one.
    """
    start, paths, base, policy = task
    return [(start + offset, verify_one(path, base, policy))
            for offset, path in enumerate(paths)]


def _chunks(paths, workers: int):
    """Split into enough batches to keep every worker fed, but no more.

    Several batches per worker rather than exactly one, so a batch of large
    files does not leave the other workers idle at the end.
    """
    batches = max(1, min(len(paths), workers * 4))
    size = max(1, (len(paths) + batches - 1) // batches)
    for start in range(0, len(paths), size):
        yield start, paths[start:start + size]


def _serial(paths, base, policy, progress):
    total = len(paths)
    for index, path in enumerate(paths, start=1):
        relative, result = verify_one(path, base, policy)
        if progress:
            progress(index, total, relative)
        yield relative, result


def _parallel(paths, base, policy, workers, progress):
    """Fan the files out, then put the answers back in the original order.

    Order is restored deliberately: completion order depends on scheduling, and
    a verdict that depends on scheduling is not a verdict.
    """
    from concurrent.futures import ProcessPoolExecutor

    total = len(paths)
    collected: dict[int, tuple] = {}
    try:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(verify_chunk, (start, batch, base, policy))
                for start, batch in _chunks(paths, workers)
            ]
            _drain(futures, collected, total, progress)
    except (OSError, RuntimeError, ImportError):
        # No usable process pool — a restricted sandbox, a platform without
        # fork. Falling back is right: slower is a inconvenience, not answering
        # is a failure.
        yield from _serial(paths, base, policy, progress)
        return

    for index in range(total):
        if index in collected:
            yield collected[index]


def _drain(futures, collected: dict, total: int, progress) -> None:
    """Collect finished batches, reporting progress as they land."""
    from concurrent.futures import as_completed

    done = 0
    for future in as_completed(futures):
        for index, outcome in future.result():
            collected[index] = outcome
            done += 1
            if progress:
                progress(done, total, outcome[0])


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
