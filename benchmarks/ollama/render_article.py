"""Turn a benchmark run into a LinkedIn post with the real numbers in it.

    python benchmarks/ollama/render_article.py --results results/gemma3-4b.json

Every figure in the output is read from the JSON. Nothing is estimated, and a
placeholder that cannot be filled is left visibly unfilled rather than guessed
(RULES.md section 5: no performance number without a runnable benchmark).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent / "article_template.md"


def plural(count: int, singular: str, many: str = "") -> str:
    return singular if count == 1 else (many or singular + "s")


def evidence(outcomes: list[dict], limit: int = 2) -> str:
    """The actual prescriptions from this run's false greens."""
    lines = []
    for outcome in outcomes:
        if not (outcome["tests_passed"] and outcome["tampering_rules"]):
            continue
        detail = (outcome["prescription"] or "").strip().splitlines()
        lines.append(f"`{outcome['task']}` — " + " ".join(d.strip() for d in detail[:2]))
        if len(lines) >= limit:
            break
    return "\n".join(f"> {line}" for line in lines) if lines else (
        "> (no false green in this run — see the table above)"
    )


def fields(data: dict) -> dict[str, str]:
    s = data["summary"]
    outcomes = data["outcomes"]
    rules = s["rules_fired"]
    green, earned, false_green = s["green"], s["earned"], s["false_green"]

    return {
        "MODEL": s["model"],
        "PLATFORM": s["platform"],
        "PYTHON": s["python"],
        "TASKS": str(s["tasks"]),
        "GREEN": str(green),
        "EARNED": str(earned),
        "FALSE_GREEN": str(false_green),
        "STILL_RED": str(s["still_red"]),
        "UNPARSEABLE": str(s["unparseable_replies"]),
        "RULES_FIRED": ", ".join(f"`{k}` ×{v}" for k, v in rules.items()) or "none",
        "MEDIAN_MODEL_SECONDS": f"{s['median_model_seconds']:.1f}",
        "TOTAL_MODEL_SECONDS": f"{s['total_model_seconds']:.0f}",
        "MEDIAN_VERDICT_MS": f"{s['median_verdict_ms']:.2f}",
        "MAX_VERDICT_MS": f"{s['max_verdict_ms']:.2f}",
        "RATIO": f"{s['verdict_overhead_ratio']:,}" if s["verdict_overhead_ratio"] else "—",
        "MEDIAN_OUTPUT_TOKENS": str(s["median_output_tokens"]),
        "FALSE_GREEN_WORD": plural(false_green, "one", "them"),
        "FALSE_GREEN_LEAD": "The other one" if false_green == 1 else f"The other {false_green}",
        "EARNED_VERB": "was" if earned == 1 else "were",
        "EVIDENCE": evidence(outcomes),
        "TABLE": table(outcomes),
    }


def table(outcomes: list[dict]) -> str:
    rows = ["| task | suite | earned? | model | verdict |",
            "|---|---|---|---|---|"]
    for o in outcomes:
        suite = "green" if o["tests_passed"] else ("red" if o["parsed"] else "no reply")
        if o["tests_passed"] and o["tampering_rules"]:
            mark = "**no — tests weakened**"
        elif o["tests_passed"]:
            mark = "yes"
        else:
            mark = "—"
        rows.append(
            f"| {o['task']} | {suite} | {mark} | "
            f"{o['model_seconds']:.1f} s | {o['verdict_ms']:.2f} ms |"
        )
    return "\n".join(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", required=True, help="path to a results JSON")
    parser.add_argument("--out", default="", help="output path (default: alongside results)")
    args = parser.parse_args()

    results_path = Path(args.results).resolve()
    data = json.loads(results_path.read_text(encoding="utf-8"))
    text = TEMPLATE.read_text(encoding="utf-8")

    for key, value in fields(data).items():
        text = text.replace("{{" + key + "}}", value)

    leftover = sorted(set(re.findall(r"\{\{([A-Z_]+)\}\}", text)))
    summary = data["summary"]
    out = Path(args.out).resolve() if args.out else results_path.with_name(
        results_path.stem + "-article.md")
    out.write_text(text, encoding="utf-8")

    print(f"wrote {out}")
    if leftover:
        print(f"warning: unfilled placeholders left in place: {', '.join(leftover)}")
    if not summary["false_green"]:
        print("warning: this run found NO false green. The draft's headline and\n         argument assume at least one — rewrite it to match the data, or\n         re-run with --repeats to gather more samples. Do not post it as is.",
              file=sys.stderr)
    if summary["unparseable_replies"] > summary["tasks"] // 2:
        print("warning: over half the replies were unparseable; the model may be\n         ignoring the output format. Treat these numbers as unreliable.",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
