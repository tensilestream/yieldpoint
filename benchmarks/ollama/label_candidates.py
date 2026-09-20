"""Label mined candidates with a local model, provisionally.

    python benchmarks/ollama/label_candidates.py --model gemma4 --limit 200

Each candidate is a real assertion removed from a real test. Whether that was
legitimate — the test moved, the feature went away, the assertion was
redundant — is a judgement. This asks a local model for that judgement and
records the answer as **provisional**.

Two rules this file exists to enforce:

*Provisional labels are not ground truth.* A dataset labelled by a model, then
used to score that same model, measures nothing. Labels here are a triage
layer: they narrow thousands of candidates to the ones worth a human read.

*The labeller is recorded.* Every row carries which model produced it, so a
later reader can discard them wholesale if the labeller is the system under
test.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ollama_client import OllamaUnavailable, converse, resolve_model  # noqa: E402

RESULTS = Path(__file__).resolve().parent / "results"

SYSTEM = (
    "You review changes to test files in open-source projects.\n\n"
    "You are shown an assertion that a commit removed or changed, and the "
    "commit's subject line.\n\n"
    "Decide whether removing it LOST verification the project still needed, or "
    "was LEGITIMATE — the test moved, the feature was deleted, the assertion "
    "was redundant, or the change strengthened the suite.\n\n"
    "Reply with exactly one word on the first line: LOST or LEGITIMATE."
)

USER = (
    "Project: {repo}\n"
    "Commit: {subject}\n"
    "File: {file}\n"
    "Rule that fired: {rule}\n"
    "What happened: {detail}\n"
    "Text removed: {before}\n"
)


def read_candidates(path: Path, limit: int) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return rows[:limit] if limit else rows


def ask(model: str, row: dict, seed: int) -> tuple[str, int, float]:
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": USER.format(
            repo=row["repo"], subject=row["subject"], file=row["file"],
            rule=row["rule"], detail=row["detail"],
            before=row.get("before") or "(the text was not recorded)")},
    ]
    reply = converse(model, messages, temperature=0.0, seed=seed)
    upper = reply.text.upper()
    first = upper.strip().splitlines()[0] if upper.strip() else ""
    for line in (first, upper):
        if "LEGITIMATE" in line and "LOST" not in line:
            return "legitimate", reply.prompt_tokens + reply.output_tokens, reply.seconds
        if "LOST" in line and "LEGITIMATE" not in line:
            return "lost", reply.prompt_tokens + reply.output_tokens, reply.seconds
    return "", reply.prompt_tokens + reply.output_tokens, reply.seconds


def label_all(rows: list[dict], model: str, seed: int) -> tuple[dict, int, float]:
    """Stamp every row. The labeller is recorded on each one, not just once."""
    counts = {"lost": 0, "legitimate": 0, "": 0}
    tokens, seconds = 0, 0.0
    for index, row in enumerate(rows):
        label, spent, took = ask(model, row, seed + index)
        row["label"] = label
        row["label_source"] = f"model:{model}"
        row["label_confidence"] = "provisional"
        tokens += spent
        seconds += took
        counts[label] += 1
        if index % 10 == 0:
            print(f"    {index + 1}/{len(rows)}  {label or 'no answer':11} "
                  f"{row['repo']}/{row['file'][:34]}")
    return counts, tokens, seconds


def write_rows(rows: list[dict]) -> Path:
    out = RESULTS / "candidates-labelled.jsonl"
    with out.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    return out


def build_summary(model: str, rows: list[dict], counts: dict,
                  tokens: int, seconds: float) -> dict:
    return {
        "labeller": f"model:{model}",
        "confidence": "provisional",
        "labelled": len(rows),
        "lost": counts["lost"],
        "legitimate": counts["legitimate"],
        "no_answer": counts[""],
        "tokens": tokens,
        "seconds": round(seconds, 1),
        "warning": "Model-produced labels. Not ground truth. Do not score this "
                   "model, or any model, against them without a human-labelled "
                   "sample to estimate label quality first.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="gemma4")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--candidates", default=str(RESULTS / "candidates.jsonl"))
    args = parser.parse_args()

    source = Path(args.candidates)
    if not source.exists():
        print(f"error: {source} not found; run mine_history.py first", file=sys.stderr)
        return 2

    try:
        model = resolve_model(args.model)
    except OllamaUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    rows = read_candidates(source, args.limit)
    print(f"  labelling {len(rows)} candidate(s) with {model}\n")
    try:
        counts, tokens, seconds = label_all(rows, model, args.seed)
    except OllamaUnavailable as exc:
        print(f"\nerror: {exc}", file=sys.stderr)
        return 2

    out = write_rows(rows)
    summary = build_summary(model, rows, counts, tokens, seconds)
    (RESULTS / "candidates-labelled-summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")

    print(f"\n  lost {counts['lost']}  legitimate {counts['legitimate']}  "
          f"no answer {counts['']}")
    print(f"  {tokens:,} tokens, {seconds:.0f}s, on your machine")
    print(f"\n  wrote {out}")
    print(f"  {summary['warning']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
