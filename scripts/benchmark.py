"""Reproducible timings. RULES.md section 5: no number without one of these.

    python scripts/benchmark.py

Measures the three paths that matter, on synthetic inputs generated here so the
run does not depend on anything outside the repository. Absolute numbers vary
with hardware; the shapes do not, and the shapes are the point.
"""

from __future__ import annotations

import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aegisflow import ledger                                    # noqa: E402
from aegisflow.harness import Change, tier                      # noqa: E402
from aegisflow.scan import scan                                 # noqa: E402
from aegisflow.totals import totals                             # noqa: E402
from aegisflow.verify import verify_change                      # noqa: E402

POLICY = {"protected_tests": ["**/test_*.py"]}


def _time(fn, repeats: int = 5) -> float:
    """Median milliseconds, so one slow run does not set the number."""
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000)
    return statistics.median(samples)


def _suite(tests: int, weaken: bool = True) -> tuple[str, str]:
    before = "\n".join(
        f"def test_case_{i}():\n    assert value_{i} == {i}\n" for i in range(tests)
    )
    after = before.replace("assert value_0 == 0", "assert value_0") if weaken else before
    return before, after


def verdict_latency() -> None:
    print("\nverify_change — one test file")
    print(f"  {'tests in file':>14} {'median ms':>11} {'ms per test':>13}")
    for tests in (1, 10, 50, 200, 400):
        before, after = _suite(tests)
        elapsed = _time(lambda: verify_change(before, after, "tests/test_x.py", POLICY))
        print(f"  {tests:>14,} {elapsed:>11.2f} {elapsed / tests:>13.2f}")
    print("  Superlinear and converging: most cost is parsing, which is linear;")
    print("  pairing renamed tests is not. Typical files sit in the first rows.")


def routing_latency() -> None:
    print("\nharness.tier — the routing decision, for comparison")
    before, after = _suite(50, weaken=False)
    change = Change("src/module.py", before, after + "\ndef extra():\n    return 1\n")
    elapsed = _time(lambda: tier(change, POLICY), repeats=20)
    print(f"  {elapsed:.2f} ms, and no model call. The alternative is a round trip.")


def ledger_latency() -> None:
    print("\nledger — the per-turn running total")
    print(f"  {'events':>10} {'median ms':>11}")
    verdict = verify_change(*_suite(1), "tests/test_x.py", POLICY)
    event = ledger.observe(verdict, "benchmark", analysed_chars=1_000)
    for count in (100, 1_000, 10_000):
        path = Path(tempfile.mkdtemp()) / "metrics.jsonl"
        for _ in range(count):
            ledger.record(event, path)
        totals(path)  # warm the incremental cache, as a real session would be
        ledger.record(event, path)
        elapsed = _time(lambda: totals(path), repeats=20)
        print(f"  {count:>10,} {elapsed:>11.2f}")
    print("  Flat by design: the fold is incremental, so a long session does not")
    print("  make every later verdict slower. See totals.py.")


def cache_effect() -> None:
    """What the analysis cache is worth, and where it is not worth anything.

    The asymmetry is the point. A repository scan re-reads files that have not
    changed, so nearly everything is a hit. Verifying an edit compares a stored
    before-state with an after-state the agent has just composed — and content
    that has never existed cannot have been cached. No amount of indexing
    changes that half.
    """
    from aegisflow.core import parsecache

    root = Path(tempfile.mkdtemp())
    package = root / "pkg"
    package.mkdir()
    for i in range(120):
        (package / f"module_{i}.py").write_text(
            f"import os\n\n" + "\n".join(
                f"def fn_{i}_{j}(a, b):\n"
                f"    if a > {j}:\n        return b\n    return a\n"
                for j in range(8)
            )
        )
    parsecache.configure(root)
    parsecache.clear()

    print("\nanalysis cache")
    cold = _time(lambda: scan(root, jobs=1), repeats=1)
    parsecache.clear()
    warm = _time(lambda: (parsecache.clear(), scan(root, jobs=1)), repeats=3)
    print(f"  scan, 120 files          cold {cold:7.0f} ms   warm {warm:7.0f} ms"
          f"   {cold / max(warm, 0.01):.1f}x")

    before, after = _suite(200)
    _time(lambda: verify_change(before, after, "tests/test_x.py", POLICY), repeats=1)
    edits = _time(
        lambda: verify_change(before, after.replace("value_1", "value_9"),
                              "tests/test_x.py", POLICY),
        repeats=5,
    )
    print(f"  verify an edit           {edits:7.0f} ms"
          "   (before cached, after always new)")
    parsecache.close()
    parsecache.configure(".")


def scan_throughput() -> None:
    print("\nscan — a whole repository")
    root = Path(tempfile.mkdtemp())
    for i in range(1_200):
        package = root / f"src/pkg{i % 40}"
        package.mkdir(parents=True, exist_ok=True)
        (package / "__init__.py").write_text("")
        (package / f"module_{i}.py").write_text(
            "import os\n\n" + "\n".join(
                f"def fn_{j}(a, b):\n    return a + b + {j}\n" for j in range(6)
            )
        )
    print(f"  {'jobs':>6} {'seconds':>9} {'files/s':>9}")
    baseline = None
    for jobs in (1, 4, None):
        start = time.perf_counter()
        result = scan(root, jobs=jobs)
        elapsed = time.perf_counter() - start
        baseline = baseline or elapsed
        label = "auto" if jobs is None else str(jobs)
        print(f"  {label:>6} {elapsed:>9.2f} {result.files / elapsed:>9.0f}")
    print("  Parallel output is byte-identical to serial; that is asserted in")
    print("  tests, and is the only reason parallelism is permitted here.")


def main() -> None:
    print("AegisFlow benchmark — numbers are for this machine, shapes are the point.")
    verdict_latency()
    routing_latency()
    ledger_latency()
    cache_effect()
    scan_throughput()
    print("\nNo figure in this repository's documentation may exceed what this prints.")


if __name__ == "__main__":
    main()
