"""Same task, same model, same turn budget — with Yieldpoint and without.

    python benchmarks/ollama/ab_experiment.py --model gemma3:4b --max-turns 4

Produces a paired result per task: what the loop landed on when its only gate
was `pytest`, and what it landed on when the test contract had to survive too.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from arms import (  # noqa: E402
    OPENING, SYSTEM, WITH, WITHOUT, ArmResult, Attempt, TurnRecord, feedback, satisfied,
)
from grading import PytestUnavailable, ensure_pytest, grade, run_pytest  # noqa: E402
from ollama_client import OllamaUnavailable, converse, parse_files, resolve_model  # noqa: E402
from run_benchmark import baseline_failure, materialise  # noqa: E402
from abreport import (  # noqa: E402
    compare, paired_table, token_verdict, verdict_label, write_results,
)
from tasks import TASKS, Task  # noqa: E402


def apply_and_test(task: Task, files: dict[str, str]) -> tuple[bool, str]:
    workdir = Path(tempfile.mkdtemp(prefix="yp-ab-"))
    try:
        materialise(task, workdir, files)
        return run_pytest(workdir)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def evaluate_turn(task: Task, text: str) -> tuple[Attempt, float, str]:
    """Parse one reply, run the suite, and grade the test transition."""
    files = parse_files(text)
    if task.module_path not in files and task.test_path not in files:
        return Attempt(False, False, (), ""), 0.0, "reply could not be parsed"

    passed, tail = apply_and_test(task, files)
    after_test = files.get(task.test_path, task.test_src)
    rules, _status, prescription, verdict_ms = grade(
        task.name, task.test_path, task.test_src, after_test
    )
    return Attempt(True, passed, tuple(rules), prescription), verdict_ms, tail


@dataclass(frozen=True)
class Settings:
    """Everything both arms must share for the comparison to mean anything."""

    max_turns: int
    temperature: float
    seed: int


def run_arm(task: Task, model: str, arm: str, settings: Settings) -> ArmResult:
    """One arm of one task. The loop is identical; only `satisfied` differs."""
    failure = baseline_failure(task)
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": OPENING.format(
            module_path=task.module_path, module_src=task.module_src,
            test_path=task.test_path, test_src=task.test_src, failure=failure)},
    ]

    history: list[TurnRecord] = []
    attempt = Attempt(False, False, (), "")
    total_model_s = total_verdict_ms = 0.0
    total_out = total_in = 0

    for turn in range(1, settings.max_turns + 1):
        prompt_chars = sum(len(m["content"]) for m in messages)
        reply = converse(model, messages, temperature=settings.temperature,
                         seed=settings.seed + turn)
        attempt, verdict_ms, failure = evaluate_turn(task, reply.text)

        total_model_s += reply.seconds
        total_verdict_ms += verdict_ms
        total_out += reply.output_tokens
        total_in += reply.prompt_tokens
        history.append(TurnRecord(
            turn, attempt.parsed, attempt.tests_passed, attempt.tampering_rules,
            reply.seconds, verdict_ms, reply.output_tokens,
            reply.prompt_tokens, prompt_chars, reply.generated_chars,
            len(reply.thinking)))

        if satisfied(arm, attempt) or turn == settings.max_turns:
            break
        messages.append({"role": "assistant", "content": reply.text})
        messages.append({"role": "user",
                         "content": feedback(arm, attempt, failure)})

    return ArmResult(
        task=task.name, arm=arm, turns_used=len(history),
        tests_passed=attempt.tests_passed, tampering_rules=attempt.tampering_rules,
        prescription=attempt.prescription, model_seconds=total_model_s,
        verdict_ms=total_verdict_ms, output_tokens=total_out,
        prompt_tokens=total_in, history=history,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="gemma3:4b")
    parser.add_argument("--max-turns", type=int, default=4,
                        help="turn budget, identical for both arms (default: %(default)s)")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--only", default="", help="comma-separated task names")
    return parser


def select(only: str) -> tuple[Task, ...]:
    if not only:
        return TASKS
    wanted = {name.strip() for name in only.split(",")}
    return tuple(task for task in TASKS if task.name in wanted)


def run_pair(task: Task, model: str, args) -> tuple[ArmResult, ArmResult]:
    """Both arms of one task, same seed, same budget."""
    out = []
    for arm in (WITHOUT, WITH):
        print(f"    {arm:>8}: ", end="", flush=True)
        result = run_arm(task, model, arm, Settings(
            args.max_turns, args.temperature, args.seed))
        print(f"{verdict_label(result):>12}  ({result.turns_used} turn(s), "
              f"{result.model_seconds:.1f}s)")
        out.append(result)
    return out[0], out[1]


def main() -> int:
    args = build_parser().parse_args()
    try:
        ensure_pytest()
    except PytestUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    selected = select(args.only)
    if not selected:
        print(f"error: no task matched {args.only!r}", file=sys.stderr)
        return 2

    try:
        model = resolve_model(args.model)
        print(f"model: {model}   tasks: {len(selected)}   "
              f"turn budget: {args.max_turns} per arm\n")
        pairs = []
        for task in selected:
            print(f"  {task.name}")
            pairs.append(run_pair(task, model, args))
    except OllamaUnavailable as exc:
        print(f"\nerror: {exc}", file=sys.stderr)
        return 2

    summary = compare(pairs, model, args.max_turns)
    json_path = write_results(pairs, summary, model)
    print("\n" + paired_table(pairs))
    print("\nTOKENS — measured by the daemon, not estimated")
    print(token_verdict(summary))
    cal = summary.get("calibration", {})
    out, inp = cal.get("output", {}), cal.get("prompt", {})
    if out.get("samples"):
        print(f"\nCHARS_PER_TOKEN calibration, against ledger.CHARS_PER_TOKEN = 4")
        print(f"  generated text ({out['samples']} samples, the clean measurement)")
        print(f"    {out['reading']}")
    if inp.get("samples"):
        print(f"  prompt text ({inp['samples']} samples)")
        print(f"    {inp['reading']}")
        print(f"    {inp['caveat']}")
    print("\n" + json.dumps(summary, indent=2, sort_keys=True))
    print(f"\nwrote {json_path}")

    from htmlproof import regenerate
    page = regenerate()
    if page:
        print(f"wrote {page}  (open it for the proof page)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
