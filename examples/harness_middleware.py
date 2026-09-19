"""Routing and gating in an agent loop — what it costs, and what it saves.

``python examples/harness_middleware.py``

Two insertion points, saving different things.

**Before the model.** Choosing which model to spend is itself a decision, and
asking a model to make it adds a round trip to save one. Read it off the syntax
tree instead: free, and the same answer every time.

**Before the tool.** A bad edit that lands costs the test run, the failure
output, the model's reasoning about the failure, and the retry. Refusing it up
front replaces all of that with one sentence saying what to restore.

The token figures below are the *measured* character counts of what the loop
would have carried, converted at a stated ratio. They are arithmetic on real
sizes, not a benchmark of anyone's agent — see `yieldpoint stats` for the same
distinction.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from yieldpoint.harness import Change, middleware

CHARS_PER_TOKEN = 4

POLICY = {"protected_tests": ["**/test_*.py"]}
TIERS = {"small": "cheap-model", "standard": "mid-model", "capable": "frontier-model"}

PLAIN = "import os\n\ndef price(a):\n    \"\"\"Old wording.\"\"\"\n    return a\n"

WORK = [
    ("reword a docstring", "src/pricing.py", PLAIN,
     "import os\n\ndef price(a):\n    \"\"\"New wording.\"\"\"\n    return a\n"),
    ("rename a local", "src/pricing.py", PLAIN,
     "import os\n\ndef price(amount):\n    \"\"\"Old wording.\"\"\"\n    return amount\n"),
    ("add a function and an import", "src/pricing.py", PLAIN,
     "import json\nimport os\n\ndef price(a):\n    \"\"\"Old wording.\"\"\"\n    return a\n\n"
     "def discount(a, pct):\n    if pct > 0:\n        return a * (1 - pct)\n    return a\n"),
    ("restructure the module", "src/pricing.py", PLAIN,
     "import json\nimport os\n\nclass Pricing:\n"
     + "\n".join(f"    def rule_{i}(self, a):\n        return a + {i}\n" for i in range(40))),
    ("edit a protected test", "tests/test_pricing.py",
     "from pricing import price\n\ndef test_price():\n    assert price(10) == 10\n",
     "from pricing import price\n\ndef test_price():\n    assert price(10)\n"),
]


def routing_table() -> None:
    mw = middleware(policy=POLICY, tiers=TIERS, escalate_to="ask-a-person")
    print("BEFORE THE MODEL — which model does this work actually need?\n")
    print(f"  {'work':<30}{'risk':<11}{'tier':<11}{'model':<16}why")
    print("  " + "-" * 100)
    for label, path, before, after in WORK:
        change = Change(path, before, after)
        decisions = mw.assess(change)
        print(f"  {label:<30}{decisions['risk']['value']:<11}"
              f"{decisions['tier']['value']:<11}"
              f"{str(mw.model_name(change)):<16}{decisions['tier']['reason']}")
    print("\n  Every row above cost one parse and no round trip. Sending all five")
    print("  to the frontier model is the default an agent loop falls into.")


def gate_saving() -> None:
    """What refusing a bad edit up front replaces."""
    tmp = Path(tempfile.mkdtemp())
    test = tmp / "test_pricing.py"
    test.write_text("from pricing import price\n\ndef test_price():\n    assert price(10) == 10\n")
    previous = Path.cwd()
    os.chdir(tmp)
    try:
        mw = middleware(policy=POLICY)
        gate = mw.before_tool("Edit", {
            "file_path": str(test),
            "old_string": "assert price(10) == 10",
            "new_string": "assert price(10)",
        })
        print("\n\nBEFORE THE TOOL — judge the edit, not the test run\n")
        print(f"  decision   {'ALLOW' if gate.allowed else 'DENY'}")
        print(f"  because    {gate.reason}")
        print(f"  instead    {gate.prescription.strip().splitlines()[-1].strip()}")

        instead = gate.prescription
        # What the loop carries when a bad edit is allowed to land instead.
        avoided = (
            len(test.read_text()) * 2      # the file, read back after failing
            + 1800                          # a pytest failure trace
            + 2400                          # the model's reasoning about it
        )
        print(f"\n  carried now        ~{len(instead) // CHARS_PER_TOKEN:>6,} tokens"
              "   (the prescription, assembled not generated)")
        print(f"  carried otherwise  ~{avoided // CHARS_PER_TOKEN:>6,} tokens"
              "   (file + failure trace + reasoning + retry)")
        print("\n  Those are character counts of real text at 4 chars/token, not a")
        print("  benchmark of your agent. The retry round trip is the real cost and")
        print("  is not counted here at all.")
    finally:
        os.chdir(previous)


def main() -> None:
    routing_table()
    gate_saving()


if __name__ == "__main__":
    main()
