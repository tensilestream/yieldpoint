"""What an LLM-as-judge actually costs, measured rather than estimated.

    python benchmarks/ollama/judge_experiment.py --model gemma4

`yp stats` prices the judge alternative as `analysed_chars / 4`. That is stated
arithmetic, not a measurement. This runs a real judge over the repository's own
labelled corpus — 18 tampering cases that must be caught, 19 legitimate
refactors that must not be — and reports what it cost and how often it was
right, beside the same numbers for Yieldpoint.

Both see identical inputs. The corpus labels are the ground truth, so this
measures accuracy, not agreement with Yieldpoint: a case where they differ is
scored against the label, whichever of them was wrong.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ollama_client import OllamaUnavailable, converse, resolve_model  # noqa: E402
from tests.corpus.legitimate import LEGITIMATE  # noqa: E402
from tests.corpus.tampering import TAMPERING  # noqa: E402
from yieldpoint.core.verdict import Status  # noqa: E402
from yieldpoint.verify import verify_change  # noqa: E402

POLICY = {"test_contract": {"protected_patterns": ["**/test_*.py", "**/*_test.py"]}}

JUDGE_SYSTEM = (
    "You review changes to test files. You are given a test file before and "
    "after an edit.\n\n"
    "Answer this question: did the edit WEAKEN what the tests verify — that is, "
    "does the suite now check less than it did before?\n\n"
    "A refactor that preserves what is checked is NOT a weakening. Renaming, "
    "reformatting, splitting a test, or adding assertions are NOT weakenings.\n\n"
    "Reply with exactly one word on the first line: WEAKENED or INTACT."
)

JUDGE_USER = "=== BEFORE ===\n{before}\n=== AFTER ===\n{after}\n=== END ===\n"


@dataclass(frozen=True)
class Row:
    case: str
    label: str
    provenance: str
    yp_flagged: bool
    yp_status: str
    yp_ms: float
    judge_flagged: bool | None
    judge_tokens: int
    judge_seconds: float
    judge_reply: str

    @property
    def truth(self) -> bool:
        return self.label == "tampering"

    @property
    def yp_correct(self) -> bool:
        return self.yp_flagged == self.truth

    @property
    def judge_correct(self) -> bool | None:
        if self.judge_flagged is None:
            return None
        return self.judge_flagged == self.truth


def yieldpoint_verdict(case) -> tuple[bool, str, float]:
    """Zero model calls, by construction. Timed anyway."""
    start = time.perf_counter()
    verdict = verify_change(case.before, case.after, case.path, POLICY)
    elapsed = (time.perf_counter() - start) * 1000
    flagged = verdict.status not in (Status.PASS, Status.UNVERIFIED)
    return flagged, verdict.status.value, elapsed


def ask_judge(model: str, case, seed: int) -> tuple[bool | None, int, float, str]:
    """One judge call. Tokens include hidden reasoning, which is a real cost."""
    messages = [
        {"role": "system", "content": JUDGE_SYSTEM},
        {"role": "user", "content": JUDGE_USER.format(
            before=case.before, after=case.after)},
    ]
    reply = converse(model, messages, temperature=0.0, seed=seed)
    tokens = reply.prompt_tokens + reply.output_tokens
    return _read_answer(reply.text), tokens, reply.seconds, reply.text.strip()[:120]


def _read_answer(text: str) -> bool | None:
    """WEAKENED / INTACT, or None when the judge did not answer the question."""
    upper = text.upper()
    first = upper.strip().splitlines()[0] if upper.strip() else ""
    for line in (first, upper):
        if "WEAKENED" in line and "INTACT" not in line:
            return True
        if "INTACT" in line and "WEAKENED" not in line:
            return False
    return None


def confusion(rows: list[Row], flagged, correct) -> dict:
    """Where each approach was wrong, not just how often."""
    scored = [r for r in rows if correct(r) is not None]
    missed = [r.case for r in scored if r.truth and not flagged(r)]
    false_alarm = [r.case for r in scored if not r.truth and flagged(r)]
    return {
        "scored": len(scored),
        "unanswered": len(rows) - len(scored),
        "correct": sum(1 for r in scored if correct(r)),
        "accuracy": round(sum(1 for r in scored if correct(r)) / len(scored), 3)
        if scored else None,
        "missed_tampering": missed,
        "false_alarms": false_alarm,
    }


def summarise(rows: list[Row], model: str) -> dict:
    judge_tokens = [r.judge_tokens for r in rows if r.judge_tokens]
    total_tokens = sum(judge_tokens)
    return {
        "model": model,
        "cases": len(rows),
        "tampering": sum(1 for r in rows if r.truth),
        "legitimate": sum(1 for r in rows if not r.truth),
        "yieldpoint": {
            **confusion(rows, lambda r: r.yp_flagged, lambda r: r.yp_correct),
            "model_calls": 0,
            "tokens": 0,
            "total_ms": round(sum(r.yp_ms for r in rows), 2),
            "median_ms": round(statistics.median([r.yp_ms for r in rows]), 3),
        },
        "llm_judge": {
            **confusion(rows, lambda r: r.judge_flagged, lambda r: r.judge_correct),
            "model_calls": len(judge_tokens),
            "tokens": total_tokens,
            "median_tokens_per_verdict": int(statistics.median(judge_tokens))
            if judge_tokens else 0,
            "total_seconds": round(sum(r.judge_seconds for r in rows), 1),
            "median_seconds": round(
                statistics.median([r.judge_seconds for r in rows]), 1),
        },
    }


def extrapolate(summary: dict, verdicts: int) -> dict:
    """What the judge alternative would have cost over a real ledger.

    Measured cost per verdict times the number of verdicts actually recorded —
    which is still an extrapolation, but from a measured unit cost rather than
    from a characters-per-token constant.
    """
    per = summary["llm_judge"]["median_tokens_per_verdict"]
    return {
        "verdicts": verdicts,
        "measured_tokens_per_verdict": per,
        "projected_judge_tokens": per * verdicts,
        "projected_judge_calls": verdicts,
        "yieldpoint_tokens": 0,
        "yieldpoint_calls": 0,
        "note": "unit cost measured on this corpus; real changes are larger, "
                "so treat this as a floor.",
    }


def render(rows: list[Row], summary: dict) -> str:
    yp, judge = summary["yieldpoint"], summary["llm_judge"]
    lines = [
        "",
        f"{'':34} {'Yieldpoint':>12} {'LLM judge':>12}",
        f"{'accuracy on 37 labelled cases':34} "
        f"{_pct(yp['accuracy']):>12} {_pct(judge['accuracy']):>12}",
        f"{'missed tampering (false negative)':34} "
        f"{len(yp['missed_tampering']):>12} {len(judge['missed_tampering']):>12}",
        f"{'false alarms on legitimate code':34} "
        f"{len(yp['false_alarms']):>12} {len(judge['false_alarms']):>12}",
        f"{'did not answer':34} {yp['unanswered']:>12} {judge['unanswered']:>12}",
        f"{'model calls':34} {yp['model_calls']:>12,} {judge['model_calls']:>12,}",
        f"{'tokens':34} {yp['tokens']:>12,} {judge['tokens']:>12,}",
        f"{'median per verdict':34} {'0':>12} "
        f"{judge['median_tokens_per_verdict']:>12,}",
        f"{'wall clock':34} {_ms(yp['total_ms']):>12} "
        f"{judge['total_seconds']:>11.0f}s",
    ]
    return "\n".join(lines)


def _pct(value) -> str:
    return "—" if value is None else f"{value:.0%}"


def _ms(value: float) -> str:
    return f"{value:.0f} ms"


def labelled() -> list[tuple[str, object]]:
    return ([("tampering", c) for c in TAMPERING]
            + [("legitimate", c) for c in LEGITIMATE])


def run_case(model: str, label: str, case, seed: int, judge: bool) -> Row:
    flagged, status, ms = yieldpoint_verdict(case)
    answer, tokens, seconds, reply = (None, 0, 0.0, "")
    if judge:
        answer, tokens, seconds, reply = ask_judge(model, case, seed)
    return Row(case.name, label, case.provenance, flagged, status, ms,
               answer, tokens, seconds, reply)


def _progress(index: int, total: int, row: Row, judge: bool) -> None:
    mark = "ok " if row.yp_correct else "YP MISS"
    if not judge:
        verdict = ""
    elif row.judge_correct is None:
        verdict = " JUDGE NO-ANSWER"
    elif row.judge_correct:
        verdict = " judge ok "
    else:
        verdict = " JUDGE WRONG"
    print(f"{mark}{verdict}  ({row.judge_tokens:,} tok)")


def run_all(model: str, cases, seed: int, judge: bool) -> list[Row]:
    rows: list[Row] = []
    for index, (label, case) in enumerate(cases):
        print(f"  [{index + 1}/{len(cases)}] {case.name[:46]:46} ", end="", flush=True)
        row = run_case(model, label, case, seed + index, judge)
        rows.append(row)
        _progress(index, len(cases), row, judge)
    return rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="gemma4")
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--limit", type=int, default=0,
                        help="only the first N cases of each class")
    parser.add_argument("--verdicts", type=int, default=268,
                        help="ledger size to extrapolate the judge cost over")
    parser.add_argument("--no-judge", action="store_true",
                        help="Yieldpoint side only; makes no model call at all")
    return parser


def select(limit: int) -> list[tuple[str, object]]:
    if not limit:
        return labelled()
    tamper = [c for c in labelled() if c[0] == "tampering"][:limit]
    legit = [c for c in labelled() if c[0] == "legitimate"][:limit]
    return tamper + legit


def main() -> int:
    args = build_parser().parse_args()
    cases = select(args.limit)
    judge = not args.no_judge

    try:
        model = resolve_model(args.model) if judge else "none"
    except OllamaUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"model: {model}   cases: {len(cases)} "
          f"({sum(1 for c in cases if c[0] == 'tampering')} tampering, "
          f"{sum(1 for c in cases if c[0] == 'legitimate')} legitimate)\n")

    try:
        rows = run_all(model, cases, args.seed, judge)
    except OllamaUnavailable as exc:
        print(f"\nerror: {exc}", file=sys.stderr)
        return 2

    summary = summarise(rows, model)
    summary["extrapolation"] = extrapolate(summary, args.verdicts)
    print(render(rows, summary))

    results = Path(__file__).resolve().parent / "results"
    results.mkdir(exist_ok=True)
    out = results / f"judge-{model.replace(':', '-')}.json"
    out.write_text(json.dumps(
        {"summary": summary, "rows": [asdict(r) for r in rows]},
        indent=2, sort_keys=True), encoding="utf-8")
    print(f"\nwrote {out}")

    from htmlproof import regenerate
    page = regenerate()
    if page:
        print(f"wrote {page}  (open it for the proof page)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
