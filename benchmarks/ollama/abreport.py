"""Turning a paired A/B run into numbers and a table.

Separated from the loop so the thing that *measures* and the thing that
*reports* can be read independently — and so neither file has to be skimmed to
review the other.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from arms import WITH, WITHOUT, ArmResult
from tokens import Sample, both_sides

def verdict_label(result: ArmResult) -> str:
    if result.false_green:
        return "FALSE GREEN"
    if result.earned:
        return "earned"
    return "still red"


def paired_table(pairs: list[tuple[ArmResult, ArmResult]]) -> str:
    rows = [
        "| task | without: outcome | turns | with: outcome | turns |",
        "|---|---|---|---|---|",
    ]
    for without, with_ in pairs:
        rows.append(
            f"| {without.task} | {verdict_label(without)} | {without.turns_used} "
            f"| {verdict_label(with_)} | {with_.turns_used} |"
        )
    return "\n".join(rows)


def _outcomes(results: list[ArmResult]) -> dict:
    """How the arm ended up, per task."""
    return {
        "tasks": len(results),
        "green": sum(1 for r in results if r.tests_passed),
        "earned": sum(1 for r in results if r.earned),
        "false_green": sum(1 for r in results if r.false_green),
        "still_red": sum(1 for r in results if not r.tests_passed),
    }


def _cost(results: list[ArmResult], earned: int) -> dict:
    """What the arm spent to get there, from the daemon's own counters."""
    spent = sum(r.total_tokens for r in results)
    return {
        "total_turns": sum(r.turns_used for r in results),
        "total_model_seconds": round(sum(r.model_seconds for r in results), 1),
        "total_verdict_ms": round(sum(r.verdict_ms for r in results), 2),
        "prompt_tokens": sum(r.prompt_tokens for r in results),
        "output_tokens": sum(r.output_tokens for r in results),
        "total_tokens": spent,
        # The figure that actually matters: tokens per outcome you can trust.
        "tokens_per_earned": round(spent / earned) if earned else None,
    }


def arm_summary(results: list[ArmResult], arm: str) -> dict:
    outcomes = _outcomes(results)
    return {"arm": arm, **outcomes, **_cost(results, outcomes["earned"])}


def token_samples(pairs) -> tuple[list[Sample], list[Sample]]:
    """Every (characters, true tokens) pair the daemon reported this run."""
    prompt, output = [], []
    for arms_ in pairs:
        for result in arms_:
            for turn in result.history:
                if turn.prompt_tokens:
                    prompt.append(Sample(turn.prompt_chars, turn.prompt_tokens))
                if turn.output_tokens:
                    # output_chars already includes hidden reasoning.
                    output.append(Sample(turn.output_chars, turn.output_tokens))
    return prompt, output


def compare(pairs: list[tuple[ArmResult, ArmResult]], model: str,
            max_turns: int) -> dict:
    without = [p[0] for p in pairs]
    with_ = [p[1] for p in pairs]
    a, b = arm_summary(without, WITHOUT), arm_summary(with_, WITH)
    prompt_samples, output_samples = token_samples(pairs)
    return {
        "model": model,
        "max_turns_per_arm": max_turns,
        "without": a,
        "with": b,
        "delta": {
            "earned": b["earned"] - a["earned"],
            "false_green": b["false_green"] - a["false_green"],
            "extra_turns": b["total_turns"] - a["total_turns"],
            "extra_model_seconds": round(
                b["total_model_seconds"] - a["total_model_seconds"], 1),
            "extra_tokens": b["total_tokens"] - a["total_tokens"],
            "verification_cost_ms": b["total_verdict_ms"],
            "verification_tokens": 0,
        },
        "calibration": both_sides(prompt_samples, output_samples),
        "rescued": sorted(
            w.task for w, v in pairs if w.false_green and v.earned),
        "unrescued": sorted(
            w.task for w, v in pairs if w.false_green and not v.earned),
    }


def token_verdict(summary: dict) -> str:
    """State the token result plainly, including when it goes the wrong way.

    A benchmark that can only confirm the hoped-for direction is advocacy. If
    the gated loop costs more tokens, that is the finding, and the honest
    comparison is cost per outcome you can actually trust.
    """
    a, b, delta = summary["without"], summary["with"], summary["delta"]
    extra = delta["extra_tokens"]
    lines = [
        f"  without: {a['total_tokens']:,} tokens -> {a['earned']} earned, "
        f"{a['false_green']} false green",
        f"  with:    {b['total_tokens']:,} tokens -> {b['earned']} earned, "
        f"{b['false_green']} false green",
    ]
    if extra > 0:
        lines.append(
            f"\n  Yieldpoint cost {extra:,} MORE model tokens ({extra / a['total_tokens']:+.0%}). "
            f"It buys correctness, not tokens.")
    elif extra < 0:
        lines.append(f"\n  Yieldpoint cost {abs(extra):,} FEWER model tokens "
                     f"({extra / a['total_tokens']:+.0%}).")
    else:
        lines.append("\n  Identical token spend.")

    lines.append(
        f"  Verification itself cost {delta['verification_tokens']} tokens and "
        f"{b['total_verdict_ms']:.0f} ms — that part is architectural, not estimated.")
    if a["tokens_per_earned"] and b["tokens_per_earned"]:
        lines.append(
            f"  Tokens per earned green: {a['tokens_per_earned']:,} without, "
            f"{b['tokens_per_earned']:,} with.")
    elif not a["earned"]:
        lines.append("  Without Yieldpoint, no green was earned at all, so cost "
                     "per trustworthy outcome is undefined.")
    return "\n".join(lines)


def write_results(pairs, summary: dict, model: str) -> Path:
    results = Path(__file__).resolve().parent / "results"
    results.mkdir(exist_ok=True)
    stem = "ab-" + model.replace(":", "-").replace("/", "-")

    payload = {
        "summary": summary,
        "pairs": [{"without": asdict(w), "with": asdict(v)} for w, v in pairs],
    }
    json_path = results / f"{stem}.json"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    (results / f"{stem}.md").write_text(
        f"# {model}: with Yieldpoint vs without, "
        f"{summary['max_turns_per_arm']} turns each\n\n"
        + paired_table(pairs) + "\n\n```json\n"
        + json.dumps(summary, indent=2, sort_keys=True) + "\n```\n",
        encoding="utf-8",
    )
    return json_path
