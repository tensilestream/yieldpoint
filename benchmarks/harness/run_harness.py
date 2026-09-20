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
from repo_tasks import REPOS, RepoTask, discover_tasks, source_files  # noqa: E402
from yieldpoint.verify import verify_diff  # noqa: E402

RESULTS = Path(__file__).resolve().parent / "results"


@dataclass
class ArmResult:
    arm: str
    control_passed: bool
    baseline_failed: bool
    tests_pass: bool
    rules: list[str]
    verification_status: str
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
    root = Path(tempfile.mkdtemp(prefix=f"yieldpoint-{task.name}-"))
    target = root / "checkout"
    _command("git", "worktree", "add", "--detach", str(target), task.sha, cwd=source)
    return root, target


def _source_reversion(task: RepoTask, checkout: Path) -> None:
    """Keep the fix's regression test, but restore only its production code."""
    source = REPOS / task.repo
    parent = _command("git", "rev-parse", f"{task.sha}^", cwd=source).strip()
    for path in source_files(task):
        result = subprocess.run(("git", "show", f"{parent}:{path}"), cwd=source,
                                text=True, capture_output=True, check=False)
        target = checkout / path
        if result.returncode:
            target.unlink(missing_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(result.stdout, encoding="utf-8")
    _command("git", "add", "-A", cwd=checkout)
    _command("git", "-c", "user.name=Yieldpoint Harness", "-c",
             "user.email=harness@example.invalid", "commit", "-m", "source-only reversion", cwd=checkout)


def _install(command: tuple[str, ...], checkout: Path) -> None:
    result = subprocess.run(command, cwd=checkout, text=True, capture_output=True, check=False)
    if result.returncode:
        detail = (result.stdout + result.stderr)[-4000:]
        raise RuntimeError(f"setup failed: {' '.join(command)}\n{detail}")


def _prepare(task: RepoTask, checkout: Path) -> str:
    """Install checkout-local dependencies; setup time is outside agent timing."""
    if (checkout / "package-lock.json").is_file():
        _install(("npm", "ci"), checkout)
        if "tests/module/esm" in task.test_command:
            module = checkout / "tests" / "module" / "esm"
            _install(("npm", "ci"), module)
            link = module / "node_modules" / "axios"
            if not link.exists():
                link.symlink_to(checkout, target_is_directory=True)
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


class UnrunnableTask(RuntimeError):
    """A task whose baseline does not hold, so no comparison it produces means
    anything.

    Distinct from a failure of the thing under test: the usual cause is a
    missing build step or an absent toolchain, and reporting that as "the agent
    failed" would be a confident, wrong answer. Carries the output so the cause
    is in the report rather than in a scrollback somebody has to still have.
    """

    def __init__(self, task: str, command: str, output: str) -> None:
        self.task, self.command = task, command
        self.output = (output or "").strip()[-600:]
        super().__init__(f"{task}: baseline does not hold for `{command}`")


def _run_arm(task: RepoTask, model: str, arm: str, max_turns: int, seed: int) -> ArmResult:
    workspace, checkout = _checkout(task)
    try:
        test_command = _prepare(task, checkout)
        control = subprocess.run(test_command, shell=True, cwd=checkout,
                                 check=False, capture_output=True, text=True)
        if control.returncode:
            raise UnrunnableTask(task.name, test_command, control.stdout + control.stderr)
        _source_reversion(task, checkout)
        baseline = subprocess.run(test_command, shell=True, cwd=checkout, check=False)
        if baseline.returncode == 0:
            raise UnrunnableTask(task.name, test_command,
                                 "reverting the source left the suite green, so the "
                                 "task measures nothing")
        start = time.perf_counter()
        settings = AgentSettings(model, str(checkout), test_command, arm == "gated", max_turns,
                                 seed=seed)
        state = run_agent(task.instruction, settings)
        test = subprocess.run(test_command, shell=True, cwd=checkout, check=False)
        diff = _command("git", "diff", cwd=checkout)
        verdict = verify_diff(diff, root=str(checkout))
        rules = sorted({finding.rule for finding in verdict.findings})
        return ArmResult(arm, True, True, test.returncode == 0, rules, verdict.status.value, int(state.get("turns", 0)),
                         int(state.get("tool_calls", 0)), int(state.get("prompt_tokens", 0)),
                         int(state.get("output_tokens", 0)), round(time.perf_counter() - start, 3),
                         list(state.get("history", [])))
    finally:
        source = REPOS / task.repo
        subprocess.run(("git", "worktree", "remove", "--force", str(checkout)), cwd=source, check=False)
        shutil.rmtree(workspace, ignore_errors=True)


def _pair(task, model: str, max_turns: int, seed: int) -> dict | None:
    """Both arms of one task, or None when its baseline does not hold."""
    arms = [_run_arm(task, model, arm, max_turns, seed) for arm in ("ungated", "gated")]
    return {"task": asdict(task), "arms": [asdict(arm) for arm in arms]}


def _select(tasks, only: str):
    """Filter by name or repository, so one task can be iterated on alone."""
    if not only:
        return tasks
    wanted = {name.strip() for name in only.split(",")}
    return [t for t in tasks if t.name in wanted or t.repo in wanted]


def _gather(tasks, model: str, max_turns: int, seed: int):
    """Both arms of every task. A task whose baseline does not hold is recorded
    with its cause rather than dropped: a list pruned to the ones that worked
    is not a measurement."""
    rows, unrunnable = [], []
    for task in tasks:
        try:
            rows.append(_pair(task, model, max_turns, seed))
        except UnrunnableTask as exc:
            unrunnable.append({"task": exc.task, "command": exc.command,
                               "why": exc.output})
    return rows, unrunnable


def _why_nothing_ran(unrunnable: list[dict]) -> str:
    lines = []
    for entry in unrunnable:
        tail = entry["why"].splitlines()[-1] if entry["why"] else "no output"
        lines.append(f"  {entry['task']}: {tail}")
    return "every candidate task was unrunnable:\n" + "\n".join(lines)


def run(model: str, max_turns: int, seed: int, only: str = "") -> dict:
    tasks = _select(discover_tasks(), only)
    if not tasks:
        raise RuntimeError(f"no candidate tasks found for {only!r}" if only
                           else "no candidate tasks found")
    ensure_host_tools(tasks)

    rows, unrunnable = _gather(tasks, model, max_turns, seed)
    if not rows:
        raise RuntimeError(_why_nothing_ran(unrunnable))

    unprovoked = [row["task"]["name"] for row in rows if not any(
        turn["rules"] for arm in row["arms"] for turn in arm["per_turn"])]
    return {"model": model, "max_turns": max_turns, "seed": seed, "results": rows,
            "targets_not_provoked": unprovoked, "unrunnable": unrunnable}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="gemma4")
    parser.add_argument("--max-turns", type=int, default=5)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--only", default="",
                        help="task name or repo, comma separated")
    args = parser.parse_args()
    try:
        report = run(resolve_model(args.model), args.max_turns, args.seed,
                     args.only)
    except (OllamaUnavailable, RuntimeError) as exc:
        print(f"harness: {exc}", file=sys.stderr)
        return 2
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / f"harness-{report['model'].replace('/', '-')}.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for skipped in report.get("unrunnable", []):
        print(f"  skipped {skipped['task']}: baseline does not hold for "
              f"`{skipped['command']}`")
    if report.get("unrunnable"):
        print()
    print("task                 arm       tests  turns  tools  prompt  output  seconds  verdict     rules")
    for row in report["results"]:
        for arm in row["arms"]:
            print(f"{row['task']['name'][:20]:20} {arm['arm']:9} {str(arm['tests_pass']):5} "
                  f"{arm['turns']:5} {arm['tool_calls']:6} {arm['prompt_tokens']:7} "
                  f"{arm['output_tokens']:7} {arm['seconds']:7.2f} {arm['verification_status']:11} "
                  f"{','.join(arm['rules']) or '-'}")
    print(f"targets_not_provoked: {', '.join(report['targets_not_provoked']) or '-'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
