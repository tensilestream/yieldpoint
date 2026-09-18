# AegisFlow Coding Standards

Condensed from [RULES.md](../../RULES.md). Read that for the reasoning.

## Rule 1: 300-line limit
No file exceeds 300 lines of code, excluding docstrings and blank lines. Split at 250.

## Rule 2: Cohesive modules
One responsibility per module, named for that responsibility. No `utils.py` / `helpers.py`
dumping grounds.

## Rule 3: SOLID & DRY
One engine. Path normalisation, assertion ranking and policy loading exist exactly once in
`aegisflow.core`; every adapter calls into it. Duplicated checks drift, and a verifier that
drifts is worthless.

## Rule 4: Language allocation
- Verification core and framework adapters: **Python**, no runtime dependencies.
- Other surfaces call the core; none reimplements a check.
- Rust is a later rewrite justified by polyglot single-implementation, not by speed.

## Rule 5: Determinism (hard constraint)
No model calls, no wall-clock, no randomness, no network, no environment reads in the
verification path. Same input, byte-identical output, any machine. Findings sorted by a
stable key.

## Rule 6: Honesty
- No performance claim without a committed runnable benchmark.
- A check that did not run reports "not evaluated" — never a green result.
- Plain names for real mechanisms.
