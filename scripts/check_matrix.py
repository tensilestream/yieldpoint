"""Every language against every check, measured.

    python scripts/check_matrix.py
    python scripts/check_matrix.py --markdown

The cross product is mostly empty and says so. Contract rules work in every
language this reads, because a weakened assertion has a shape a regular
expression can see. Structure and refactor rules need a syntax tree, and this
package ships a parser for Python only — that is a real limit, printed as one
rather than left for a reader to discover.

A cell is only a pass if the weakening is reported *and* the unchanged file is
not. Half a detector is not coverage.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from langchecks import CASES, STATES  # noqa: E402
from yieldpoint.core.verdict import Status  # noqa: E402
from yieldpoint.verify import verify_change  # noqa: E402

POLICY = {
    "test_contract": {
        "protected_patterns": [
            "**/tests/**", "**/test/**", "**/test_*.py", "**/*_test.*",
            "**/*.test.*", "**/*Test.*", "**/*Tests.*", "**/*Spec.*",
        ],
        "assertion_monotonicity": "block",
        "forbid_vacuous_assertions": "block",
        "forbid_new_skip_markers": "block",
        "forbid_swallowed_exceptions": "block",
    }
}

#: Rules that need a syntax tree, so they reach Python and nothing else yet.
PYTHON_ONLY = (
    "file_too_long", "function_too_long", "complexity_too_high",
    "nesting_too_deep", "too_many_parameters", "duplicate_implementation",
    "duplicate_across_files", "utility_module", "dangling_reference",
    "export_removed", "boundary_violation", "weak_new_test",
)

#: Rules decided on a file's content rather than its language.
LANGUAGE_AGNOSTIC = ("ci_check_removed", "ci_check_disabled", "change_too_large")


def cell(case, state: str, rule: str) -> str:
    """One (language, check) result: pass, miss, or not expressible."""
    after = getattr(case, state)
    if after is None:
        return "n/a"
    reported = verify_change(case.strong, after, case.path, POLICY)
    if not any(f.rule == rule for f in reported.findings):
        return "MISS"
    unchanged = verify_change(case.strong, case.strong, case.path, POLICY)
    return "pass" if not unchanged.findings else "NOISY"


def measure() -> list[dict]:
    return [
        {"language": case.language,
         "results": {rule: cell(case, state, rule) for state, rule in STATES}}
        for case in CASES
    ]


def _grid(rows: list[dict], rules: list[str]) -> list[str]:
    """The table itself, one line per language."""
    width = max(len(r["language"]) for r in rows)
    head = f"  {'':{width}}  " + "  ".join(f"{r.split('_')[0][:9]:>9}" for r in rules)
    return [head] + [
        f"  {row['language']:{width}}  "
        + "  ".join(f"{row['results'][r]:>9}" for r in rules)
        for row in rows
    ]


def _tally(rows: list[dict], rules: list[str]) -> list[str]:
    """What passed, what is missing, and what was never expressible."""
    values = [v for row in rows for v in row["results"].values()]
    total = sum(1 for v in values if v != "n/a")
    passed = sum(1 for v in values if v == "pass")
    missed = [(row["language"], rule) for row in rows
              for rule, value in row["results"].items()
              if value in ("MISS", "NOISY")]

    out = ["", f"  {passed}/{total} expressible cells pass "
               f"({len(values) - total} not expressible in that language)"]
    if missed:
        out.append(f"  gaps: {', '.join(f'{a}/{b}' for a, b in missed)}")
    return out


def _scope() -> list[str]:
    """The rules this grid does not cover, and why."""
    return [
        "",
        f"  Python-only rules ({len(PYTHON_ONLY)}): these need a syntax tree",
        f"    {', '.join(PYTHON_ONLY)}",
        f"  language-agnostic ({len(LANGUAGE_AGNOSTIC)}): decided on content",
        f"    {', '.join(LANGUAGE_AGNOSTIC)}",
    ]


def plain(rows: list[dict]) -> str:
    rules = [rule for _state, rule in STATES]
    return "\n".join(_grid(rows, rules) + _tally(rows, rules) + _scope())


def markdown(rows: list[dict]) -> str:
    rules = [rule for _state, rule in STATES]
    lines = ["| Language | " + " | ".join(f"`{r}`" for r in rules) + " |",
             "|---" * (len(rules) + 1) + "|"]
    for row in rows:
        cells = " | ".join(
            {"pass": "yes", "n/a": "—", "MISS": "**no**", "NOISY": "**noisy**"}[
                row["results"][r]] for r in rules)
        lines.append(f"| {row['language']} | {cells} |")
    lines.append("")
    lines.append("`—` means the language has no such construct: Go has no skip "
                 "decorator, Rust has no swallowed-assertion idiom. Nothing is "
                 "claimed for a cell that was not tested.")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args()
    rows = measure()
    print(markdown(rows) if args.markdown else plain(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
