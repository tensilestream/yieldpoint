"""Run real historical bug fixes through identical gated and ungated agents."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = (str(ROOT), str(Path(__file__).resolve().parent))

from langgraph_agent import AgentSettings, run_agent  # noqa: E402
from ollama_client import OllamaUnavailable, resolve_model  # noqa: E402
from prepare import ensure_host_tools  # noqa: E402
from repo_tasks import REPOS, RepoTask, discover_tasks  # noqa: E402
from yieldpoint.verify import verify_diff  # noqa: E402

RESULTS = Path(__file__).resolve().parent / "results"


@dataclass
class ArmResult:
    arm: str
    tests_pass: bool
    rules: list[str]
    turns: int
    tool_calls: int
    prompt_tokens: int
    output_tokens: int
    seconds: float
    per_turn: list[dict]


def _command(*args: str, cwd: Path) -> str:
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=True).stdout


def _checkout(task: RepoTask) -> tuple[Path, Path]:
    source = REPOS / task.repo
    parent = _command("git", "rev-parse", f"{task.sha}^", cwd=source).strip()
    root = Path(tempfile.mkdtemp(prefix=f"yieldpoint-{task.name}-"))
    target = root / "checkout"
    _command("git", "worktree", "add", "--detach", str(target), parent, cwd=source)
    return root, target


def _install(command: tuple[str, ...], checkout: Path) -> None:
    result = subprocess.run(command, cwd=checkout, text=True, capture_output=True, check=False)
    if result.returncode:
        detail = (result.stdout + result.stderr)[-4000:]
        raise RuntimeError(f"setup failed: {' '.join(command)}\n{detail}")


def _prepare(task: RepoTask, checkout: Path) -> str:
    """Install checkout-local dependencies; setup time is outside agent timing."""
    if (checkout / "package-lock.json").is_file():
        _install(("npm", "ci"), checkout)
        return task.test_command
    if task.test_command.startswith("python "):
        python = checkout / ".venv" / "bin" / "python"
        _install((sys.executable, "-m", "venv", "--system-site-packages", ".venv"), checkout)
        _install((str(python), "-m", "pip", "install", "-e", ".", "pytest"), checkout)
        return task.test_command.replace("python", str(python), 1)
    if task.test_command.startswith("cargo "):
        _install(("cargo", "fetch"), checkout)
    if task.test_command.startswith("go "):
        _install(("go", "mod", "download"), checkout)
    if task.test_command.startswith("mvn "):
        _install(("mvn", "dependency:go-offline"), checkout)
    if task.test_command.startswith("bundle "):
        _install(("bundle", "install"), checkout)
    return task.test_command


def _run_arm(task: RepoTask, model: str, arm: str, max_turns: int, seed: int) -> ArmResult:
    workspace, checkout = _checkout(task)
    try:
        test_command = _prepare(task, checkout)
        start = time.perf_counter()
        settings = AgentSettings(model, str(checkout), test_command, arm == "gated", max_turns,
                                 seed=seed)
        state = run_agent(task.instruction, settings)
        test = subprocess.run(test_command, shell=True, cwd=checkout, check=False)
        diff = _command("git", "diff", cwd=checkout)
        verdict = verify_diff(diff, root=str(checkout))
        rules = sorted({finding.rule for finding in verdict.findings})
        return ArmResult(arm, test.returncode == 0, rules, int(state.get("turns", 0)),
                         int(state.get("tool_calls", 0)), int(state.get("prompt_tokens", 0)),
                         int(state.get("output_tokens", 0)), round(time.perf_counter() - start, 3),
                         list(state.get("history", [])))
    finally:
        source = REPOS / task.repo
        subprocess.run(("git", "worktree", "remove", "--force", str(checkout)), cwd=source, check=False)
        shutil.rmtree(workspace, ignore_errors=True)


def run(model: str, max_turns: int, seed: int) -> dict:
    tasks = discover_tasks()
    if len(tasks) != 3:
        raise RuntimeError(f"needed three runnable tasks, found {len(tasks)}")
    ensure_host_tools(tasks)
    rows = []
    for task in tasks:
        arms = [_run_arm(task, model, arm, max_turns, seed) for arm in ("ungated", "gated")]
        rows.append({"task": asdict(task), "arms": [asdict(arm) for arm in arms]})
    unprovoked = [row["task"]["name"] for row in rows if not any(
        turn["rules"] for arm in row["arms"] for turn in arm["per_turn"])]
    return {"model": model, "max_turns": max_turns, "seed": seed, "results": rows,
            "targets_not_provoked": unprovoked}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="gemma4")
    parser.add_argument("--max-turns", type=int, default=5)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    try:
        report = run(resolve_model(args.model), args.max_turns, args.seed)
    except (OllamaUnavailable, RuntimeError) as exc:
        print(f"harness: {exc}", file=sys.stderr)
        return 2
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / f"harness-{report['model'].replace('/', '-')}.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("task                 arm       tests  turns  tools  prompt  output  seconds  rules")
    for row in report["results"]:
        for arm in row["arms"]:
            print(f"{row['task']['name'][:20]:20} {arm['arm']:9} {str(arm['tests_pass']):5} "
                  f"{arm['turns']:5} {arm['tool_calls']:6} {arm['prompt_tokens']:7} "
                  f"{arm['output_tokens']:7} {arm['seconds']:7.2f} {','.join(arm['rules']) or '-'}")
    print(f"targets_not_provoked: {', '.join(report['targets_not_provoked']) or '-'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
