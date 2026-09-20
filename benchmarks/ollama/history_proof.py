"""Replay this repository's own history and record what would have been caught.

    python benchmarks/ollama/history_proof.py

No model, no network, no fixtures. Every commit since the root is re-verified
as the change it was when it was made, so the findings are about real code
someone actually wrote and merged.

Yieldpoint cannot tell you which findings were right — that judgement is the
point of running it on your own history rather than on a demo.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from yieldpoint import backtest  # noqa: E402
from yieldpoint.core.policy import Policy  # noqa: E402
from yieldpoint.stats import CONTRACT_RULES  # noqa: E402

RESULTS = Path(__file__).resolve().parent / "results"


def root_commit(repo: Path) -> str:
    out = subprocess.run(["git", "rev-list", "--max-parents=0", "HEAD"],
                         cwd=repo, capture_output=True, text=True, timeout=60)
    return out.stdout.split()[-1]


def evidence(repo: Path, sha: str, policy: Policy) -> list[dict]:
    """The findings for one commit, with the text that was actually removed."""
    from yieldpoint.verify import verify_diff

    diff = subprocess.run(["git", "show", "--no-color", "-U3", "--format=", sha],
                          cwd=repo, capture_output=True, text=True, timeout=60).stdout

    def read(relative: str) -> str | None:
        got = subprocess.run(["git", "show", f"{sha}:{relative}"], cwd=repo,
                             capture_output=True, text=True, timeout=60)
        return got.stdout if got.returncode == 0 else None

    verdict = verify_diff(diff, repo, policy, read=read)
    return [
        {"rule": f.rule, "file": f.file, "line": f.line, "detail": f.detail,
         "before": f.before, "prescription": f.prescription}
        for f in verdict.findings if f.rule in CONTRACT_RULES
    ]


def run(repo: Path, limit: int) -> dict:
    policy = Policy.load(str(repo / ".yieldpoint.json"))
    since = root_commit(repo)
    start = time.perf_counter()
    result = backtest.run(repo, since=since, policy=policy, limit=limit)
    elapsed = time.perf_counter() - start
    if result.reason:
        raise RuntimeError(result.reason)

    stopped = []
    for commit in result.flagged:
        if not commit.contract_rules:
            continue
        stopped.append({
            "sha": commit.sha[:10],
            "subject": commit.subject,
            "rules": list(commit.contract_rules),
            "findings": evidence(repo, commit.sha, policy),
        })

    return {
        "repository": repo.name,
        "commits_replayed": len(result.commits),
        "commits_flagged": len(result.flagged),
        "commits_a_correctness_rule_would_have_stopped": len(stopped),
        "seconds": round(elapsed, 1),
        "model_calls": 0,
        "tokens": 0,
        "stopped": stopped,
    }


def report(data: dict) -> str:
    lines = [
        f"  repository                 {data['repository']}",
        f"  commits replayed           {data['commits_replayed']}",
        f"  commits flagged            {data['commits_flagged']}",
        f"  a correctness rule would",
        f"    have stopped             {data['commits_a_correctness_rule_would_have_stopped']}",
        f"  time                       {data['seconds']}s",
        f"  model calls                {data['model_calls']}",
        f"  tokens                     {data['tokens']}",
        "",
    ]
    for commit in data["stopped"]:
        lines.append(f"  {commit['sha']}  {commit['subject'][:52]}")
        for finding in commit["findings"]:
            lines.append(f"      {finding['file']}:{finding['line']}  "
                         f"[{finding['rule']}]")
            if finding["before"]:
                lines.append(f"      removed: {finding['before'][:78]}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=str(ROOT),
                        help="any git repository (default: this one)")
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    if not (repo / ".git").exists():
        print(f"error: {repo} is not a git repository", file=sys.stderr)
        return 2

    try:
        data = run(repo, args.limit)
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(report(data))
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / "history.json"
    out.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"\n  wrote {out}")

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from htmlproof import regenerate
    page = regenerate()
    if page:
        print(f"  wrote {page}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
