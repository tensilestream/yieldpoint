"""Would the pre-edit brief have warned, before the rule fired?

Replays a ledger in recorded order and asks, for each finding, whether the
same ``file::rule`` had already been seen. That is exactly the line
``brief`` now prints, so the answer is what the brief would have said.

What this does not establish: the ledger records that a rule fired on a path,
never whether the code in between was repaired. An unfixed finding re-fires on
every review and is counted here as a warning that would have landed. The hit
rate is therefore an **upper bound** on prevention, not a measure of it. The
recurrence figure below is printed alongside so the inflation is visible
rather than buried.
"""

from __future__ import annotations

import argparse
from collections import Counter

from yieldpoint.ledger import DEFAULT_PATH, load


def replay(events) -> dict:
    """Walk the ledger forwards, counting what history already knew."""
    seen: dict[str, set[str]] = {}
    counts = Counter()
    for event in sorted(events, key=lambda e: e.at):
        for key in event.keys:
            file, _, rule = key.partition("::")
            if not rule:
                continue
            known = seen.setdefault(file, set())
            counts["total"] += 1
            counts["same_rule" if rule in known
                   else "same_file" if known else "new_path"] += 1
            known.add(rule)
    return dict(counts)


def recurrence(events) -> tuple[int, int]:
    """Distinct ``file::rule`` pairs, and how many spanned several reviews."""
    runs = Counter()
    for event in events:
        for key in {k for k in event.keys if "::" in k}:
            runs[key] += 1
    return len(runs), sum(1 for count in runs.values() if count > 1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", default=DEFAULT_PATH)
    args = parser.parse_args()

    events = load(args.ledger)
    counts = replay(events)
    total = counts.get("total", 0)
    if not total:
        print("No findings recorded, so there is nothing to replay.")
        return 0

    share = lambda n: f"{n:5,}  ({100 * n / total:3.0f}%)"  # noqa: E731
    print(f"findings replayed                {total:5,}")
    print(f"  same rule had fired here    {share(counts.get('same_rule', 0))}")
    print(f"  another rule had fired here {share(counts.get('same_file', 0))}")
    print(f"  path was entirely new       {share(counts.get('new_path', 0))}")

    pairs, repeated = recurrence(events)
    print(f"\ndistinct file::rule pairs        {pairs:5,}")
    print(f"  seen in more than one review  {repeated:5,}  "
          f"({100 * repeated / pairs:.0f}%)")
    print("\nUpper bound, not a prevention rate: a finding left unfixed re-fires "
          "and\nis counted as a warning that would have landed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
