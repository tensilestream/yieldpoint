#!/usr/bin/env python3
"""Regenerate the shared routing fixtures that Python, Node, and Java all read.

The fixtures are the cross-language contract. Hand-writing them lets a
placeholder digest sit in the tree unnoticed, and a placeholder digest is
exactly what stops `validate_profile` from proving anything — so they are
generated from the engine instead, and a test asserts the committed copies are
current.

Run: python3 scripts/build_routing_fixtures.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from yieldpoint.harness import (  # noqa: E402
    CapsuleInput, Change, ProfileContext, admit, build_profile, build_task_capsule,
)

FIXTURES = ROOT / "fixtures" / "routing-profile"

BEFORE = "def total(items):\n    return sum(items)\n"
AFTER = "def total(items):\n    return sum(item.price for item in items)\n"

REPAIR_VERDICT = {
    "schema_version": 1,
    "status": "repair",
    "findings": [{
        "rule": "boundary_violation", "status": "repair", "file": "src/widget.py",
        "line": 2, "detail": "reaches past its layer",
        "prescription": "call the accessor instead", "confidence": "exact",
    }],
}

BLOCK_VERDICT = {
    "schema_version": 1,
    "status": "block",
    "findings": [{
        "rule": "assertion_monotonicity", "status": "block", "file": "tests/test_widget.py",
        "line": 9, "detail": "the suite now asserts less than it did",
        "prescription": "restore the removed assertion", "confidence": "exact",
    }],
}


def _profile(verdict, *, path: str = "src/widget.py", attempt: int = 0) -> dict:
    return build_profile(
        Change(path, BEFORE, AFTER),
        context=ProfileContext(verdict=verdict, repair_attempt=attempt),
    ).to_dict()


def build() -> dict[str, dict]:
    """Return every fixture by filename, derived from the engine itself."""
    repair = _profile(REPAIR_VERDICT, attempt=1)
    unverified = _profile(None)
    blocked = _profile(BLOCK_VERDICT, path="tests/test_widget.py")
    session = admit(repair, task_id="fixture-task", selected_model="standard").to_dict()
    exhausted = {**session, "switch_count": repair["handoff"]["max_model_switches"]}
    trimmed = build_task_capsule(session, repair, context=CapsuleInput(
        objective="Charge each line item at its own price",
        acceptance_criteria=("boundary_violation is cleared", "unit tests pass"),
        verdict=REPAIR_VERDICT,
        changed_paths=("src/widget.py",),
        diff_excerpt="x" * 40_000,
        test_outcomes=("pytest tests/test_widget.py: 1 failed",),
    ))
    return {
        "valid-profile.json": repair,
        "valid-session.json": session,
        "unverified-profile.json": unverified,
        "blocked-profile.json": blocked,
        "exhausted-session.json": exhausted,
        "trimmed-capsule.json": trimmed,
        # Deliberately malformed: every language must refuse it.
        "invalid-profile.json": {"schema_version": 99, "profile_id": ""},
    }


def main() -> int:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for name, document in build().items():
        (FIXTURES / name).write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"  wrote {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
