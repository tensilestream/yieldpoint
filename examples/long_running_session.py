"""A session that runs for hours, not seconds.

``python examples/long_running_session.py``

Three things go wrong in a long session, and none of them show up in a demo
that runs twenty verdicts.

**The bookkeeping stops being free.** The running total is read on every
verdict. Recomputing it from the whole ledger is O(events) per read and O(events
squared) over the session — invisible at twenty events, ruinous at twenty
thousand. ``totals()`` folds incrementally and reads only what is new.

**The loop stops making progress.** An agent can retry the same broken edit
indefinitely. A superstep counter cuts it off after N regardless; detecting the
*same structural state recurring* stops it as soon as it stops learning.

**Nobody can tell what it did.** Over six hours, "12 findings" is not a report.
Findings per agent, per rule, and the fix rate are.
"""

from __future__ import annotations

import time

from aegisflow import ledger
from aegisflow.langgraph import observe as observe_loop, signature
from aegisflow.report import render, running_line
from aegisflow.stats import summarise
from aegisflow.totals import totals
from aegisflow.verify import verify_change

POLICY = {"protected_tests": ["**/test_*.py"]}

BEFORE = "from billing import invoice\n\ndef test_total():\n    assert invoice.total == 42\n"
WEAKER = "from billing import invoice\n\ndef test_total():\n    assert invoice.total\n"
FIXED = "from billing import invoice\n\ndef test_total():\n    assert invoice.total == 99\n"


def cost_of_bookkeeping(path, rounds: int = 600) -> None:
    """Does the per-turn total stay cheap as the session goes on?"""
    samples = []
    for index in range(rounds):
        # Each round differs, so this measures cost rather than loop detection.
        after = FIXED.replace("99", str(index))
        verdict = verify_change(BEFORE, after, "tests/test_invoice.py", POLICY)
        ledger.record(
            ledger.observe(verdict, "session", analysed_chars=len(BEFORE) + len(after),
                           who=ledger.Who("long-session", f"worker-{index % 4}")),
            path,
        )
        start = time.perf_counter()
        running = totals(path)          # what the footer reads, every single turn
        samples.append((time.perf_counter() - start) * 1000)

    first = sum(samples[:20]) / 20
    last = sum(samples[-20:]) / 20
    print(f"verdicts recorded          {running.verdicts:,}")
    print(f"footer read, first 20 avg  {first:.3f} ms")
    print(f"footer read, last 20 avg   {last:.3f} ms")
    print(f"growth                     {last / first:.2f}x over {rounds} verdicts")
    print("\nIf that ratio grew with the round count, the fold would be O(n^2)")
    print("over a session and the footer would get slower all day.")
    print(f"\n{running_line(running)}")


def loop_that_stops_progressing() -> None:
    """The other long-session failure: retrying something that will never work."""
    print("\nAn agent retrying the same broken edit:")
    history: list[str] = []
    for round_number in range(1, 9):
        verdict = verify_change(BEFORE, WEAKER, "tests/test_invoice.py", POLICY)
        attempt = signature(WEAKER, *(f.rule for f in verdict.findings))
        history, stalled = observe_loop(history, attempt, window=6, max_repeats=3)
        print(f"  round {round_number}: {verdict.status.value}"
              f"{'  <- same state, same findings; stop' if stalled else ''}")
        if stalled:
            break
    print("\n  A superstep limit would have cut this off at N regardless of")
    print("  progress. This stops as soon as progress stops.")


def main() -> None:
    import tempfile
    from pathlib import Path

    path = Path(tempfile.mkdtemp()) / "metrics.jsonl"
    cost_of_bookkeeping(path)
    loop_that_stops_progressing()
    print("\n" + "=" * 68 + "\n")
    print(render(summarise(ledger.load(path))))


if __name__ == "__main__":
    main()
