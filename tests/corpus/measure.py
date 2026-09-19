"""Score the corpus and report the rates.

Kept separate from the case data so that adding a case never touches the
scoring, and from the test module so the numbers can be printed by a human
asking "what does this thing get wrong?" without running a test runner.
"""

from __future__ import annotations

from dataclasses import dataclass

from yieldpoint.core.verdict import Status
from yieldpoint.verify import verify_change

from . import LEGITIMATE, TAMPERING
from .case import HOLDOUT, TUNED

POLICY = {"protected_tests": ["**/test_*.py"]}

#: Rules that mean "this change weakened the test suite". Structural and
#: maintainability rules are excluded: they are about the shape of the code, and
#: counting them here would measure a different product.
CONTRACT_RULES = frozenset({
    "assertion_monotonicity", "vacuous_assertion",
    "empty_test", "skip_marker", "disabled_assertion",
})


@dataclass(frozen=True)
class Result:
    case: object
    fired: bool
    rules: tuple[str, ...]


def evaluate(case) -> Result:
    verdict = verify_change(case.before, case.after, case.path, POLICY)
    rules = tuple(f.rule for f in verdict.findings if f.rule in CONTRACT_RULES)
    return Result(case=case, fired=bool(rules), rules=rules)


def score(provenance: str | None = None):
    """Return ``(false_positives, false_negatives, total_legit, total_tamper)``."""
    legit = [c for c in LEGITIMATE if provenance in (None, c.provenance)]
    tamper = [c for c in TAMPERING if provenance in (None, c.provenance)]
    false_positives = [r for r in map(evaluate, legit) if r.fired]
    false_negatives = [r for r in map(evaluate, tamper) if not r.fired]
    return false_positives, false_negatives, len(legit), len(tamper)


def report() -> int:
    """Print the table. Returns a process exit code."""
    worst = 0
    for label in (TUNED, HOLDOUT, None):
        name = {TUNED: "tuned", HOLDOUT: "held out", None: "ALL"}[label]
        fps, fns, n_legit, n_tamper = score(label)
        print(f"\n{name}: {n_legit} legitimate refactors, {n_tamper} tampering patterns")
        print(f"  false positives  {len(fps)}/{n_legit}"
              f"   (legitimate refactors wrongly reported)")
        print(f"  false negatives  {len(fns)}/{n_tamper}"
              f"   (tampering not reported)")
        for result in fps:
            print(f"    FP  {result.case.name}  -> {', '.join(result.rules)}")
        for result in fns:
            print(f"    FN  {result.case.name}")
        worst = max(worst, len(fps) + len(fns))

    print("\nThe held-out numbers are the meaningful ones; the tuned cases were "
          "used\nwhile fixing the checker and a perfect score on them is expected.")
    return 1 if worst else 0
