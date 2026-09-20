"""Run every scenario and report where the claim and reality disagree.

    python benchmarks/ollama/matrix.py

Makes no model call. Each row states which rule it expects; this runs the real
verifier and records what actually came back, so a row that no longer behaves
as claimed shows up as a mismatch rather than quietly passing.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from scenarios import CHANGE_SET_RULES, POLICY, SCENARIOS, Scenario  # noqa: E402
from yieldpoint.core.verdict import Status  # noqa: E402
from yieldpoint.verify import verify_change, verify_diff  # noqa: E402

RESULTS = Path(__file__).resolve().parent / "results"


@dataclass
class Result:
    action: str
    name: str
    intent: str
    path: str
    expect: str
    rules: list[str]
    status: str
    detail: str
    prescription: str
    ms: float

    @property
    def fired(self) -> bool:
        return self.status not in ("pass", "unverified")

    @property
    def agrees(self) -> bool:
        """Did the claim hold? Both directions matter equally."""
        if self.expect:
            return self.expect in self.rules
        return not self.fired


def run(scenario: Scenario) -> Result:
    start = time.perf_counter()
    verdict = verify_change(scenario.before, scenario.after, scenario.path, POLICY)
    elapsed = (time.perf_counter() - start) * 1000
    wanted = [f for f in verdict.findings if f.rule == scenario.expect]
    shown = wanted[0] if wanted else (verdict.findings[0] if verdict.findings else None)
    return Result(
        action=scenario.action, name=scenario.name, intent=scenario.intent,
        path=scenario.path, expect=scenario.expect,
        rules=sorted({f.rule for f in verdict.findings}),
        status=verdict.status.value,
        detail=shown.detail if shown else "",
        prescription=shown.prescription if shown else "",
        ms=round(elapsed, 3),
    )


def change_set_demo() -> Result:
    """`change_too_large` is decided over a whole diff, not one file."""
    files, added = 4, 400
    content = {
        f"src/generated_{n}.py":
            "".join(f"line_{i} = {i}\n" for i in range(added))
        for n in range(files)
    }
    # `diff --git` headers matter: without them the parser sees one file, not four.
    diff = "".join(
        f"diff --git a/{path} b/{path}\nnew file mode 100644\n"
        f"--- /dev/null\n+++ b/{path}\n@@ -0,0 +1,{added} @@\n"
        + "".join(f"+{line}\n" for line in body.splitlines())
        for path, body in content.items())
    start = time.perf_counter()
    verdict = verify_diff(diff, ROOT, POLICY, read=content.get)
    elapsed = (time.perf_counter() - start) * 1000
    finding = next((f for f in verdict.findings if f.rule == "change_too_large"), None)
    return Result(
        action="one big change", name="a change too large to review",
        intent=f"land {files * added:,} lines across {files} files at once",
        path=f"{files} files", expect="change_too_large",
        rules=sorted({f.rule for f in verdict.findings}),
        status=verdict.status.value,
        detail=finding.detail if finding else "",
        prescription=finding.prescription if finding else "",
        ms=round(elapsed, 3),
    )


def duplication_demo() -> Result:
    """`duplicate_across_files` needs two files, so it needs a diff."""
    body = ("    total = 0\n    for row in rows:\n        if row.active:\n"
            "            total += row.amount\n    return total\n")
    content = {"src/invoices.py": f"def sum_invoices(rows):\n{body}",
               "src/payments.py": f"def sum_payments(rows):\n{body}"}
    diff = "".join(
        f"diff --git a/{path} b/{path}\nnew file mode 100644\n"
        f"--- /dev/null\n+++ b/{path}\n@@ -0,0 +1,{len(src.splitlines())} @@\n"
        + "".join(f"+{line}\n" for line in src.splitlines())
        for path, src in content.items())

    start = time.perf_counter()
    verdict = verify_diff(diff, ROOT, POLICY, read=content.get)
    elapsed = (time.perf_counter() - start) * 1000
    finding = next((f for f in verdict.findings
                    if f.rule == "duplicate_across_files"), None)
    return Result(
        action="one big change", name="the same function in two files",
        intent="copy the working implementation into a second module",
        path="2 files", expect="duplicate_across_files",
        rules=sorted({f.rule for f in verdict.findings}),
        status=verdict.status.value,
        detail=finding.detail if finding else "",
        prescription=finding.prescription if finding else "",
        ms=round(elapsed, 3),
    )


def summarise(results: list[Result]) -> dict:
    fire = [r for r in results if r.expect]
    clean = [r for r in results if not r.expect]
    return {
        "scenarios": len(results),
        "distinct_rules": sorted({r.expect for r in results if r.expect}),
        "must_fire": len(fire),
        "fired_as_claimed": sum(1 for r in fire if r.agrees),
        "must_stay_clean": len(clean),
        "stayed_clean": sum(1 for r in clean if r.agrees),
        "mismatches": [
            {"name": r.name, "expected": r.expect or "clean", "got": r.rules or "clean"}
            for r in results if not r.agrees
        ],
        "total_ms": round(sum(r.ms for r in results), 2),
        "model_calls": 0,
        "tokens": 0,
    }


def report(results: list[Result], summary: dict) -> None:
    action = None
    for r in results:
        if r.action != action:
            action = r.action
            print(f"\n  {action.upper()}")
        claim = r.expect or "stay clean"
        got = ", ".join(r.rules) or "clean"
        flag = "" if r.agrees else "   <-- MISMATCH"
        print(f"    {r.name:38} {claim:24} -> {got}{flag}")

    print(f"\n  {summary['fired_as_claimed']}/{summary['must_fire']} rules fired as "
          f"claimed; {summary['stayed_clean']}/{summary['must_stay_clean']} legitimate "
          f"edits stayed clean")
    print(f"  {len(summary['distinct_rules'])} distinct rules, "
          f"{summary['total_ms']:.0f} ms total, "
          f"{summary['model_calls']} model calls, {summary['tokens']} tokens")
    if summary["mismatches"]:
        print("\n  MISMATCHES")
        for m in summary["mismatches"]:
            print(f"    {m['name']}: expected {m['expected']}, got {m['got']}")


def main() -> int:
    results = ([run(s) for s in SCENARIOS]
               + [change_set_demo(), duplication_demo()])
    summary = summarise(results)
    report(results, summary)

    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / "matrix.json"
    out.write_text(json.dumps(
        {"summary": summary, "results": [asdict(r) for r in results]},
        indent=2), encoding="utf-8")
    print(f"\nwrote {out}")

    from htmlproof import regenerate
    page = regenerate()
    if page:
        print(f"wrote {page}")
    return 1 if summary["mismatches"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
