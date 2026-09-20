"""Mine real assertion removals out of real git history.

    python benchmarks/ollama/mine_history.py --repos ../a ../b
    python benchmarks/ollama/mine_history.py --clone      # a curated public set

No model and no network beyond `git clone`. Every candidate is a real commit
by a real person: the file, the commit, and the exact text that was removed.

This produces *candidates*, not labels. Whether a given removal was legitimate
is a judgement, and mining cannot make it — see label_candidates.py. A dataset
whose labels came from the tool being measured would prove nothing.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from yieldpoint.core.policy import Policy  # noqa: E402
from yieldpoint.verify import verify_diff  # noqa: E402

RESULTS = Path(__file__).resolve().parent / "results"
CACHE = Path(__file__).resolve().parent / ".repos"

#: Python projects with real test suites and enough history to be worth reading.
PUBLIC = (
    "https://github.com/psf/requests",
    "https://github.com/pallets/click",
    "https://github.com/Textualize/rich",
    "https://github.com/pallets/flask",
    "https://github.com/psf/black",
)

#: Every rule the engine can fire, so a mine says something about all of them
#: rather than only the test contract. Structure limits are the project's own
#: defaults; a repository with different conventions would set its own.
POLICY = {
    "test_contract": {
        "protected_patterns": ["**/tests/**", "**/test/**", "**/test_*.py",
                               "**/*_test.py"],
        "assertion_monotonicity": "repair",
        "forbid_vacuous_assertions": "repair",
        "forbid_new_skip_markers": "repair",
        "forbid_swallowed_exceptions": "repair",
    },
    "structure": {
        "greenfield": False, "severity": "repair",
        "max_file_lines": 300, "max_lines": 50, "max_parameters": 5,
        "max_nesting": 4, "max_complexity": 10,
        "forbid_utility_modules": True, "duplicate_implementation": "repair",
    },
    "refactor": {"dangling_reference": "repair", "export_removed": "repair"},
    "ci": {"check_removed": "repair", "check_disabled": "repair"},
}

#: Rules the engine knows about. A rule absent from a mine is reported as
#: "no real instance found", which is a result about the rule, not a gap in
#: the report.
ALL_RULES = (
    "assertion_monotonicity", "vacuous_assertion", "empty_test", "skip_marker",
    "disabled_assertion", "boundary_violation", "change_too_large",
    "ci_check_disabled", "ci_check_removed", "complexity_too_high",
    "dangling_reference", "duplicate_implementation", "export_removed",
    "file_too_long", "function_too_long", "nesting_too_deep",
    "too_many_parameters", "utility_module",
)


@dataclass(frozen=True)
class Candidate:
    repo: str
    sha: str
    subject: str
    author_date: str
    file: str
    line: int
    rule: str
    detail: str
    before: str | None
    after: str | None
    symbol: str | None = None
    label: str = ""
    """Empty until something labels it. Mining does not."""


def git(repo: Path, *args: str, timeout: int = 120) -> str:
    out = subprocess.run(["git", *args], cwd=repo, capture_output=True,
                         text=True, timeout=timeout)
    return out.stdout if out.returncode == 0 else ""


def clone(url: str) -> Path | None:
    CACHE.mkdir(exist_ok=True)
    target = CACHE / url.rstrip("/").split("/")[-1]
    if target.exists():
        return target
    print(f"    cloning {url} ... ", end="", flush=True)
    done = subprocess.run(
        ["git", "clone", "--filter=blob:none", "--no-checkout", url, str(target)],
        capture_output=True, text=True, timeout=600)
    print("ok" if done.returncode == 0 else "failed")
    return target if done.returncode == 0 else None


def worth_reading(repo: Path, sha: str) -> bool:
    """Cheap filter. Any Python or CI file can break some rule, not only tests."""
    names = git(repo, "show", "--name-only", "--format=", sha)
    return any(line.endswith((".py", ".yml", ".yaml"))
               for line in names.splitlines())


def harvest(repo: Path, sha: str, policy: Policy) -> list[Candidate]:
    diff = git(repo, "show", "--no-color", "--no-ext-diff", "-U3", "--format=", sha)
    if not diff.strip():
        return []

    def read(relative: str) -> str | None:
        return git(repo, "show", f"{sha}:{relative}") or None

    try:
        verdict = verify_diff(diff, repo, policy, read=read)
    except Exception:            # one bad commit must not end the mine
        return []

    meta = git(repo, "show", "-s", "--format=%s%n%aI", sha).splitlines()
    subject = meta[0][:90] if meta else ""
    when = meta[1] if len(meta) > 1 else ""

    return [
        Candidate(repo=repo.name, sha=sha[:12], subject=subject, author_date=when,
                  file=f.file, line=f.line, rule=f.rule, detail=f.detail,
                  before=f.before, after=f.after, symbol=f.symbol)
        for f in verdict.findings
    ]


def mine(repo: Path, limit: int, policy: Policy) -> list[Candidate]:
    shas = git(repo, "rev-list", "--no-merges", f"--max-count={limit}",
               "HEAD", timeout=300).split()
    found: list[Candidate] = []
    for index, sha in enumerate(shas):
        if index % 200 == 0 and index:
            print(f"      {index}/{len(shas)} commits, {len(found)} candidates")
        if not worth_reading(repo, sha):
            continue
        found.extend(harvest(repo, sha, policy))
    return found


def summarise(candidates: list[Candidate], repos: int) -> dict:
    from collections import Counter
    by_rule = Counter(c.rule for c in candidates)
    with_text = sum(1 for c in candidates if c.before)
    return {
        "repositories": repos,
        "candidates": len(candidates),
        "rules_with_a_real_instance": sorted(by_rule),
        "rules_with_none": sorted(r for r in ALL_RULES if r not in by_rule),
        "by_rule": dict(by_rule.most_common()),
        "carry_the_removed_text": with_text,
        "distinct_commits": len({(c.repo, c.sha) for c in candidates}),
        "labelled": sum(1 for c in candidates if c.label),
        "note": "candidates, not labels. Whether each removal was legitimate "
                "is a judgement mining cannot make.",
    }


def sources(args) -> list[Path]:
    if args.clone:
        return [p for p in (clone(url) for url in PUBLIC) if p]
    return [Path(r).resolve() for r in args.repos]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repos", nargs="*", default=[], help="local git repos")
    parser.add_argument("--clone", action="store_true",
                        help=f"clone and mine {len(PUBLIC)} public projects")
    parser.add_argument("--limit", type=int, default=2000,
                        help="commits per repository (default: %(default)s)")
    parser.add_argument("--out", default=str(RESULTS / "candidates.jsonl"))
    args = parser.parse_args()

    repos = sources(args)
    if not repos:
        print("error: pass --repos, or --clone for the public set", file=sys.stderr)
        return 2

    policy = Policy.load(POLICY)
    found: list[Candidate] = []
    for repo in repos:
        if not (repo / ".git").exists():
            print(f"  skipping {repo}: not a git repository")
            continue
        print(f"  mining {repo.name}")
        got = mine(repo, args.limit, policy)
        print(f"    {len(got)} candidate(s)")
        found.extend(got)

    RESULTS.mkdir(exist_ok=True)
    out = Path(args.out)
    with out.open("w", encoding="utf-8") as handle:
        for candidate in found:
            handle.write(json.dumps(asdict(candidate)) + "\n")

    summary = summarise(found, len(repos))
    (RESULTS / "candidates-summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")

    print(f"\n  {summary['candidates']} candidates from "
          f"{summary['distinct_commits']} commits across {len(repos)} repo(s)")
    for rule, count in summary["by_rule"].items():
        print(f"    {rule:26} {count}")
    print(f"  {summary['carry_the_removed_text']} carry the removed text")
    print(f"\n  wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
