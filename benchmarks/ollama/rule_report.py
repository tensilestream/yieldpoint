"""Totals and tables for the rule A/B.

Split from rule_ab.py so the loop and the reporting each stay inside the
length limit this project enforces on everyone else.
"""

from __future__ import annotations

from arms import WITH, WITHOUT
from rule_ab import Arm


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
