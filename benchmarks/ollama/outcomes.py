"""For every mined finding: is it still there today?

    python benchmarks/ollama/outcomes.py

A finding is only interesting if something followed from it. This checks each
candidate against the repository's current HEAD and reports one of:

  fixed      the problem is gone
  live       still present today, years later in some cases
  moved      the file no longer exists
  unknown    the finding did not record enough to check

No model. The answer comes from reading HEAD, not from asking anything.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from yieldpoint.core.metrics import measure  # noqa: E402

RESULTS = Path(__file__).resolve().parent / "results"
CACHE = Path(__file__).resolve().parent / ".repos"

LIMITS = {"function_too_long": ("lines", 50), "complexity_too_high": ("complexity", 10),
          "too_many_parameters": ("parameters", 5), "nesting_too_deep": ("nesting", 4)}

#: `before` holds what was ADDED for these, so present-in-HEAD means unfixed.
ADDED_NOT_REMOVED = ("skip_marker", "disabled_assertion", "vacuous_assertion")


def repo_for(name: str) -> Path | None:
    for base in (ROOT if name == ROOT.name else CACHE / name,):
        if (Path(base) / ".git").exists():
            return Path(base)
    return None


def head(repo: Path, path: str) -> str | None:
    got = subprocess.run(["git", "show", f"HEAD:{path}"], cwd=repo,
                         capture_output=True, text=True, timeout=60)
    return got.stdout if got.returncode == 0 else None


def _structural(source: str, row: dict) -> str:
    """Re-measure the symbol as it stands now."""
    field, limit = LIMITS[row["rule"]]
    module = measure(source, filename=row["file"])
    if not module.ok:
        return "unknown"
    named = [f for f in module.functions if f.qualname == row.get("symbol")]
    if not named:
        return "fixed"                       # the function is gone entirely
    return "live" if getattr(named[0], field) > limit else "fixed"


def normalise(text: str) -> str:
    """Compare code, not quoting.

    The recorded text comes from ``ast.unparse``, which normalises quotes and
    spacing; the file on disk has whatever the author typed. Comparing them
    raw reports a restored assertion as still missing.
    """
    return " ".join(text.replace('"', "'").split())


def verdict(repo: Path, row: dict) -> str:
    # `change_too_large` names a change set ("26 files"), not a path.
    if row["file"].endswith(" files"):
        return "not-a-file"
    source = head(repo, row["file"])
    if source is None:
        return "moved"
    if row["rule"] in LIMITS:
        return _structural(source, row)
    if not row.get("before"):
        return "unknown"
    present = normalise(row["before"]) in normalise(source)
    if row["rule"] in ADDED_NOT_REMOVED:
        return "live" if present else "fixed"
    return "fixed" if present else "live"


def analyse(rows: list[dict]) -> tuple[list[dict], dict]:
    repos: dict[str, Path | None] = {}
    by_rule: dict[str, Counter] = {}
    for row in rows:
        name = row["repo"]
        if name not in repos:
            repos[name] = repo_for(name)
        repo = repos[name]
        row["outcome"] = verdict(repo, row) if repo else "unknown"
        by_rule.setdefault(row["rule"], Counter())[row["outcome"]] += 1

    overall = Counter(r["outcome"] for r in rows)
    return rows, {
        "candidates": len(rows),
        "repositories": sorted(repos),
        "outcomes": dict(overall),
        "still_live": overall["live"],
        "by_rule": {rule: dict(counts) for rule, counts in sorted(by_rule.items())},
        "note": "live means the finding is still true of HEAD today. It does "
                "not mean the finding was right — that judgement is the "
                "reader's.",
    }


def report(summary: dict) -> str:
    lines = [
        f"  candidates      {summary['candidates']}",
        f"  still live      {summary['still_live']}",
        f"  outcomes        {summary['outcomes']}",
        "",
        f"  {'rule':26} {'live':>5} {'fixed':>6} {'moved':>6} {'unknown':>8}"
        f" {'n/a':>5}",
    ]
    for rule, counts in summary["by_rule"].items():
        lines.append(f"  {rule:26} {counts.get('live',0):>5} "
                     f"{counts.get('fixed',0):>6} {counts.get('moved',0):>6} "
                     f"{counts.get('unknown',0):>8} {counts.get('not-a-file',0):>5}")
    return "\n".join(lines)


def main() -> int:
    source = RESULTS / "candidates.jsonl"
    if not source.exists():
        print(f"error: {source} not found; run mine_history.py first", file=sys.stderr)
        return 2

    rows = [json.loads(line) for line in
            source.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows, summary = analyse(rows)

    out = RESULTS / "outcomes.jsonl"
    with out.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    (RESULTS / "outcomes-summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")

    print(report(summary))
    print(f"\n  wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
