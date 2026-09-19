"""Whether to record, where, and on whose behalf.

Split from ledger.py because the two answer different questions. That file is
how an event is written and read; this one is whether it should be written at
all, which is a question about consent and context rather than about storage.

Three things decide it, in this order:

**A committed "no" wins.** ``"metrics": {"enabled": false}`` in the policy is a
decision the project made on purpose, and nothing here overrides it.

**A test run records nothing.** A project whose own suite exercises a
verification surface would otherwise record a verdict for every assertion it
makes, and ``yieldpoint stats`` would report work nobody did. Detected rather
than left to each project to remember, because the failure is silent: the
numbers drift, running the suite twice changes them, and nothing says why.

**Otherwise it records**, unless ``YIELDPOINT_NO_METRICS`` says not to.
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from .ledger import DEFAULT_PATH, observe, record


@dataclass(frozen=True)
class Run:
    """What a surface knows about a verification that the verdict does not."""

    surface: str
    analysed: int
    elapsed: int = 0
    root: str = "."


def record_run(verdict, run: Run, policy) -> bool:
    """Record one verification. The single place every surface goes through.

    Shared rather than repeated per surface: two copies of this drift, and a
    ledger that counts differently depending on which door was used is worse
    than no ledger.
    """
    if not enabled(policy):
        return False
    return record(
        observe(verdict, run.surface, analysed_chars=run.analysed,
                duration_ms=run.elapsed),
        path_for(policy, run.root),
    )


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


def under_test() -> bool:
    """Is this process a test run?

    A project whose own tests exercise a verification surface would otherwise
    record a verdict for every assertion it makes about Yieldpoint, and
    ``yieldpoint stats`` would report work nobody did. Running the suite twice
    would change the numbers; running it in CI would corrupt them for everyone.

    Detected rather than left to each project to remember, because the failure
    is silent — the numbers simply drift, and nothing says why.

    ``python -m pytest`` and ``python -m unittest`` are both recognised, as is
    pytest's per-test variable. A test file executed directly is not, so
    ``YIELDPOINT_NO_METRICS`` remains the explicit answer for anything unusual.
    """
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    main = sys.modules.get("__main__")
    name = getattr(getattr(main, "__spec__", None), "name", "") or ""
    return name.startswith(("unittest", "pytest", "nose"))


def enabled(policy) -> bool:
    """Whether to record, honouring the policy, the environment, and context.

    ``YIELDPOINT_NO_METRICS`` switches it off without editing a committed file,
    which is what a CI job or a privacy-conscious user reaches for first.
    ``YIELDPOINT_METRICS=1`` forces it back on, for the rare case of wanting a
    test run recorded deliberately.
    """
    if os.environ.get("YIELDPOINT_NO_METRICS"):
        return False
    configured = bool(getattr(getattr(policy, "metrics", None), "enabled", True))
    if not configured:
        return False  # a committed "no" is consent, and outranks context
    if os.environ.get("YIELDPOINT_METRICS"):
        return True
    return not under_test()


def path_for(policy, root: str | Path = ".") -> Path:
    """Where this repository's ledger lives.

    Resolved to the repository root, so a command pointed at a subdirectory
    does not start a second ledger inside it.
    """
    from .core.locate import repository

    configured = getattr(getattr(policy, "metrics", None), "path", None)
    return repository(root) / (configured or DEFAULT_PATH)


__all__ = [
    "Run", "Timer", "record_run", "enabled", "under_test", "path_for",
]
