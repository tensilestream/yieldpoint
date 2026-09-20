"""The same request, answered with the gate and without it, across every family.

    python benchmarks/ollama/rule_ab.py --model gemma4 --max-turns 3

Differs from ab_experiment.py in what it gates on. That one asks whether the
test contract survived; this one asks whether *any* rule fired, so it covers
new files, new methods, rewrites, CI edits and tests in one run.

Fairness is the same as before and matters as much: identical turn budget,
identical seed, turn 1 identical in both arms, and the verdict computed in both
arms every turn — the ungated arm simply never sees it. That is how its
violations can be counted without it having been warned.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ollama_client import OllamaUnavailable, converse, parse_files, resolve_model  # noqa: E402
from rule_tasks import RULE_TASKS, RuleTask  # noqa: E402
from scenarios import POLICY  # noqa: E402
from yieldpoint.core.verdict import Status  # noqa: E402
from yieldpoint.verify import verify_change  # noqa: E402

WITHOUT, WITH = "without", "with"
RESULTS = Path(__file__).resolve().parent / "results"

SYSTEM = (
    "You are a coding agent working in an existing project. Carry out the "
    "request.\n\nReply with the complete new contents of every file you "
    "create or change, in exactly this form and nothing else:\n\n"
    "=== FILE: <path> ===\n<full file contents>\n=== END ===\n\n"
    "No commentary, no explanation, no markdown fences."
)

REQUEST = "{instruction}\n\n{context}"
REJECTED = (
    "That change was rejected by the project's checks:\n\n{prescription}\n\n"
    "Fix it and reply with the complete files again, same format."
)
UNPARSEABLE = ("That reply could not be parsed. Reply with each complete file "
               "preceded by `=== FILE: <path> ===`, and nothing else.")


@dataclass
class Turn:
    turn: int
    parsed: bool
    rules: list[str]
    prompt_tokens: int
    output_tokens: int
    seconds: float
    verdict_ms: float


@dataclass
class Arm:
    task: str
    family: str
    targets: str
    arm: str
    turns_used: int
    rules: list[str]
    status: str
    clean: bool
    files_written: list[str]
    prompt_tokens: int
    output_tokens: int
    seconds: float
    verdict_ms: float
    history: list[Turn] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.output_tokens

    @property
    def hit_target(self) -> bool:
        """Did the request actually provoke the rule it was chosen for?"""
        return self.targets in self.rules


def context(task: RuleTask) -> str:
    shown = {**task.files, **task.extra}
    if not shown:
        return "The project is empty apart from what you create."
    return "Current files:\n\n" + "".join(
        f"=== FILE: {path} ===\n{body}=== END ===\n" for path, body in shown.items())


def inspect(task: RuleTask, written: dict[str, str]) -> tuple[list[str], str, str, float]:
    """Verify every file the model wrote, against the full policy."""
    start = time.perf_counter()
    rules: set[str] = set()
    worst = Status.PASS
    prescriptions: list[str] = []
    for path, after in written.items():
        before = task.files.get(path)
        verdict = verify_change(before, after, path, POLICY)
        rules.update(f.rule for f in verdict.findings)
        if verdict.findings:
            prescriptions.append(verdict.prescription)
        if verdict.status is Status.BLOCK or (
                verdict.status is Status.REPAIR and worst is not Status.BLOCK):
            worst = verdict.status
    elapsed = (time.perf_counter() - start) * 1000
    return sorted(rules), worst.value, "\n".join(prescriptions), elapsed


@dataclass(frozen=True)
class Settings:
    """Everything both arms must share for the comparison to mean anything."""

    max_turns: int
    temperature: float
    seed: int


def run_arm(task: RuleTask, model: str, arm: str, settings: Settings) -> Arm:
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": REQUEST.format(
            instruction=task.instruction, context=context(task))},
    ]
    history: list[Turn] = []
    rules: list[str] = []
    status, prescription, written = "unverified", "", {}
    tok_in = tok_out = 0
    seconds = verdict_ms = 0.0

    for turn in range(1, settings.max_turns + 1):
        reply = converse(model, messages, temperature=settings.temperature,
                         seed=settings.seed + turn)
        tok_in += reply.prompt_tokens
        tok_out += reply.output_tokens
        seconds += reply.seconds

        produced = parse_files(reply.text)
        parsed = bool(produced)
        if parsed:
            written = produced
            rules, status, prescription, ms = inspect(task, written)
        else:
            rules, status, prescription, ms = [], "unverified", "", 0.0
        verdict_ms += ms
        history.append(Turn(turn, parsed, list(rules), reply.prompt_tokens,
                            reply.output_tokens, reply.seconds, ms))

        clean = parsed and not rules
        if arm == WITHOUT or clean or turn == settings.max_turns:
            break
        messages.append({"role": "assistant", "content": reply.text})
        messages.append({"role": "user", "content":
                         UNPARSEABLE if not parsed
                         else REJECTED.format(prescription=prescription)})

    return Arm(
        task=task.name, family=task.family, targets=task.targets, arm=arm,
        turns_used=len(history), rules=rules, status=status,
        clean=bool(written) and not rules, files_written=sorted(written),
        prompt_tokens=tok_in, output_tokens=tok_out,
        seconds=round(seconds, 1), verdict_ms=round(verdict_ms, 3),
        history=history,
    )


def side(arms: list[Arm], name: str) -> dict:
    """One arm's totals."""
    return {
        "arm": name,
        "tasks": len(arms),
        "clean": sum(1 for a in arms if a.clean),
        "with_findings": sum(1 for a in arms if a.rules),
        "unparseable": sum(1 for a in arms if not a.files_written),
        "turns": sum(a.turns_used for a in arms),
        "tokens": sum(a.total_tokens for a in arms),
        "seconds": round(sum(a.seconds for a in arms), 1),
        "verdict_ms": round(sum(a.verdict_ms for a in arms), 2),
    }


def summarise(pairs: list[tuple[Arm, Arm]], model: str, max_turns: int) -> dict:
    without = [p[0] for p in pairs]
    with_ = [p[1] for p in pairs]

    a, b = side(without, WITHOUT), side(with_, WITH)
    return {
        "model": model,
        "max_turns_per_arm": max_turns,
        "families": sorted({w.family for w in without}),
        "targets_provoked": sorted(w.targets for w in without if w.hit_target),
        "targets_not_provoked": sorted(
            w.targets for w in without if not w.hit_target),
        "without": a,
        "with": b,
        "delta": {
            "clean": b["clean"] - a["clean"],
            "extra_turns": b["turns"] - a["turns"],
            "extra_tokens": b["tokens"] - a["tokens"],
            "verification_tokens": 0,
        },
        "repaired": sorted(w.task for w, v in pairs if w.rules and v.clean),
        "unrepaired": sorted(w.task for w, v in pairs if w.rules and not v.clean),
    }


def table(pairs: list[tuple[Arm, Arm]]) -> str:
    lines = [f"  {'task':22} {'family':18} {'without':28} {'with':22} turns"]
    for w, v in pairs:
        lines.append(
            f"  {w.task:22} {w.family:18} "
            f"{(', '.join(w.rules) or 'clean')[:27]:28} "
            f"{(', '.join(v.rules) or 'clean')[:21]:22} "
            f"{w.turns_used}->{v.turns_used}")
    return "\n".join(lines)


def report(pairs: list[tuple[Arm, Arm]], summary: dict) -> None:
    print("\n" + table(pairs))
    for name in (WITHOUT, WITH):
        s = summary[name]
        print(f"  {name + ':':9} {s['clean']}/{s['tasks']} clean, "
              f"{s['tokens']:,} tokens, {s['turns']} turns")
    print(f"  repaired: {summary['repaired'] or 'none'}")
    print(f"  unrepaired: {summary['unrepaired'] or 'none'}")
    print(f"  targets the request failed to provoke: "
          f"{summary['targets_not_provoked'] or 'none'}")


def select(only: str) -> tuple[RuleTask, ...]:
    if not only:
        return RULE_TASKS
    wanted = {n.strip() for n in only.split(",")}
    return tuple(t for t in RULE_TASKS if t.name in wanted)


def run_pair(task: RuleTask, model: str, settings: Settings) -> tuple[Arm, Arm]:
    print(f"  {task.name} ({task.family})")
    arms = []
    for arm in (WITHOUT, WITH):
        result = run_arm(task, model, arm, settings)
        print(f"    {arm:>8}: {', '.join(result.rules) or 'clean':32} "
              f"({result.turns_used} turn(s), {result.seconds:.0f}s)")
        arms.append(result)
    return arms[0], arms[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="gemma4")
    parser.add_argument("--max-turns", type=int, default=3)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=5)
    parser.add_argument("--only", default="")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    tasks = select(args.only)
    if not tasks:
        print(f"error: no task matched {args.only!r}", file=sys.stderr)
        return 2

    try:
        model = resolve_model(args.model)
        print(f"model: {model}   tasks: {len(tasks)}   "
              f"turn budget: {args.max_turns} per arm\n")
        settings = Settings(args.max_turns, args.temperature, args.seed)
        pairs = [run_pair(task, model, settings) for task in tasks]
    except OllamaUnavailable as exc:
        print(f"\nerror: {exc}", file=sys.stderr)
        return 2

    summary = summarise(pairs, model, args.max_turns)
    report(pairs, summary)

    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"ruleab-{model.replace(':', '-')}.json"
    out.write_text(json.dumps(
        {"summary": summary,
         "pairs": [{"without": asdict(w), "with": asdict(v)} for w, v in pairs]},
        indent=2), encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
