"""What fraction of real weakenings does Yieldpoint actually catch?

    python benchmarks/ollama/coverage_map.py

Runs every entry in weakenings.py through the real verifier and reports where
the claim and reality disagree. No model.

The number this prints is deliberately unflattering. A coverage map that only
listed the covered cases would be a feature list; the point is to show the
shape of what is *not* covered, so the next rule is chosen from evidence.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from weakenings import ALL_WEAKENINGS, ARTIFACTS  # noqa: E402
from yieldpoint.core.verdict import Status  # noqa: E402
from yieldpoint.verify import verify_change  # noqa: E402

RESULTS = Path(__file__).resolve().parent / "results"

POLICY = {
    "test_contract": {
        "protected_patterns": ["**/tests/**", "**/test_*.py", "**/*_test.py"],
        "assertion_monotonicity": "block", "forbid_vacuous_assertions": "block",
        "forbid_new_skip_markers": "block", "forbid_swallowed_exceptions": "block",
    },
    "structure": {"greenfield": False, "severity": "repair"},
    "refactor": {"dangling_reference": "repair", "export_removed": "repair"},
    "ci": {"check_removed": "repair", "check_disabled": "repair"},
}


def check(weakening) -> dict:
    verdict = verify_change(weakening.before, weakening.after or None,
                            weakening.path, POLICY)
    rules = sorted({f.rule for f in verdict.findings})
    fired = verdict.status not in (Status.PASS, Status.UNVERIFIED)
    # Only the rule that understands this weakening counts. Anything else is
    # a coincidence and would inflate coverage.
    caught = fired and (weakening.by_rule in rules if weakening.by_rule else False)
    return {
        "incidental": fired and not caught,
        "artifact": weakening.artifact,
        "name": weakening.name,
        "path": weakening.path,
        "claimed_covered": weakening.covered,
        "caught": caught,
        "status": verdict.status.value,
        "rules": rules,
        "agrees": caught == weakening.covered,
    }


def per_artifact(rows: list[dict]) -> dict:
    """Caught-versus-total for each artifact an agent edits."""
    out = {}
    for artifact in ARTIFACTS:
        here = [r for r in rows if r["artifact"] == artifact]
        out[artifact] = {
            "total": len(here),
            "caught": sum(1 for r in here if r["caught"]),
        }
    return out


def summarise(rows: list[dict]) -> dict:
    caught = sum(1 for r in rows if r["caught"])
    by_artifact = per_artifact(rows)
    return {
        "weakenings": len(rows),
        "caught": caught,
        "missed": len(rows) - caught,
        "incidental_findings": sum(1 for r in rows if r["incidental"]),
        "coverage": round(caught / len(rows), 3),
        "artifacts": len(ARTIFACTS),
        "artifacts_fully_covered": sorted(
            a for a, v in by_artifact.items() if v["caught"] == v["total"]),
        "artifacts_with_no_coverage": sorted(
            a for a, v in by_artifact.items() if not v["caught"]),
        "by_artifact": by_artifact,
        "surprises": [
            {"name": r["name"], "claimed": r["claimed_covered"], "caught": r["caught"]}
            for r in rows if not r["agrees"]
        ],
        "rules_that_fired": dict(Counter(
            rule for r in rows for rule in r["rules"]).most_common()),
    }


def report(rows: list[dict], summary: dict) -> str:
    lines = [f"  {'artifact':18} {'caught':>7} {'total':>6}"]
    for artifact, counts in summary["by_artifact"].items():
        mark = "" if counts["caught"] else "   <- nothing"
        lines.append(f"  {artifact:18} {counts['caught']:>7} {counts['total']:>6}{mark}")
    lines.append("")
    lines.append(f"  {summary['caught']}/{summary['weakenings']} weakenings caught "
                 f"({summary['coverage']:.0%})")
    lines.append(f"  {summary['incidental_findings']} more produced a finding "
                 f"from an unrelated rule (coincidence, not coverage)")
    lines.append(f"  {len(summary['artifacts_with_no_coverage'])} of "
                 f"{summary['artifacts']} artifact kinds have no coverage at all")
    if summary["surprises"]:
        lines.append("\n  claim did not match reality:")
        for s in summary["surprises"]:
            lines.append(f"    {s['name']}: claimed {s['claimed']}, caught {s['caught']}")
    return "\n".join(lines)


def main() -> int:
    rows = [check(w) for w in ALL_WEAKENINGS]
    summary = summarise(rows)
    print(report(rows, summary))

    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / "coverage.json"
    out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2),
                   encoding="utf-8")
    print(f"\n  wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
