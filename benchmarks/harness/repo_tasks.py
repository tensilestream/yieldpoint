"""Mine small, reproducible bug-fix tasks from the cached upstream clones."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


REPOS = Path(__file__).resolve().parents[1] / "ollama" / ".repos"
COMMANDS = {
    "axios": "npm test", "clap": "cargo test", "click": "python -m pytest -q",
    "cobra": "go test ./...", "express": "npm test", "gson": "mvn test",
    "mux": "go test ./...", "requests": "python -m pytest -q", "sinatra": "bundle exec rake",
}
FIX_WORDS = ("fix", "correct", "handle", "prevent", "avoid", "resolve", "repair")
SOURCE_SUFFIXES = frozenset({".py", ".js", ".cjs", ".mjs", ".ts", ".tsx", ".go", ".rs",
                             ".java", ".kt", ".rb", ".cs", ".c", ".cc", ".cpp", ".h"})


@dataclass(frozen=True)
class RepoTask:
    name: str
    repo: str
    sha: str
    instruction: str
    test_command: str
    files: tuple[str, ...]


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(("git", *args), cwd=repo, text=True,
                            capture_output=True, check=True,
                            env={**os.environ, "GIT_NO_LAZY_FETCH": "1"})
    return result.stdout


def _paths(repo: Path, sha: str) -> tuple[int, tuple[str, ...]]:
    total, paths = 0, []
    for row in _git(repo, "show", "--format=", "--numstat", "--no-renames", sha).splitlines():
        fields = row.split("\t", 2)
        if len(fields) == 3 and fields[0].isdigit() and fields[1].isdigit():
            total += int(fields[0]) + int(fields[1])
            paths.append(fields[2])
    return total, tuple(paths)


def _is_test(path: str) -> bool:
    lowered = path.lower()
    name = Path(lowered).name
    return (lowered.startswith(("tests/", "test/", "spec/")) or "/tests/" in lowered
            or "/test/" in lowered or "/spec/" in lowered or name.startswith("test_")
            or name.endswith(("_test.py", "_test.go", "spec.rb", ".spec.js", ".test.js")))


def source_files(task: RepoTask) -> tuple[str, ...]:
    """Code changed by the fix, excluding its regression tests and metadata."""
    return tuple(path for path in task.files
                 if not _is_test(path) and Path(path).suffix.lower() in SOURCE_SUFFIXES)


def _test_command(repo: str, files: tuple[str, ...]) -> str | None:
    tests = [path for path in files if _is_test(path)]
    if repo == "axios":
        return _axios_test(tests)
    runnable = _runnable_test(tests)
    commands = {
        "express": f"npm test -- {runnable}",
        "click": f"python -m pytest -q {runnable}",
        "requests": f"python -m pytest -q {runnable}",
        "clap": "cargo test -p clap_complete",
    }
    if repo in {"express", "click", "requests"} and not runnable:
        return None
    if repo in commands:
        return commands[repo]
    return COMMANDS[repo]


def _axios_test(paths: list[str]) -> str | None:
    """Unit tests only.

    ``tests/module/esm`` is deliberately excluded. It imports axios through a
    symlink and resolves ``dist/node/axios.cjs``, which ``npm run build``
    produces — so it measures build output, not the source an agent edits.
    Without a build it cannot pass at all, and with one it still cannot see
    the agent's change. Either way it answers a different question than this
    benchmark asks.
    """
    unit = next((path for path in paths if path.startswith("tests/unit/")
                 and path.endswith(".test.js")), "")
    return f"npm test -- {unit}" if unit else None


def _runnable_test(paths: list[str]) -> str:
    return next((path for path in paths if Path(path).name.startswith("test")
                 or ".test." in Path(path).name), "")


def _task_for(repo: Path, sha: str, subject: str) -> RepoTask | None:
    try:
        changed, files = _paths(repo, sha)
    except subprocess.CalledProcessError:
        return None
    suitable = changed < 200 and any(map(_is_test, files))
    if not suitable:
        return None
    command = _test_command(repo.name, files)
    if not command:
        return None
    task = RepoTask(f"{repo.name}-{sha[:8]}", repo.name, sha,
                    _instruction(subject, files, command), command, files)
    return task if source_files(task) else None


def _instruction(subject: str, files: tuple[str, ...], command: str) -> str:
    """What the agent is asked for.

    The commit subject alone leaves the model to guess which of a few thousand
    files to open, and a small model guesses badly. Naming the source files and
    the test command is what a colleague would say, and costs no more than the
    subject did.
    """
    # Code only. A changelog is in the commit but is not the implementation,
    # and naming it first sent the model to read release notes and give up.
    sources = [path for path in files if not _is_test(path)
               and Path(path).suffix.lower() in SOURCE_SUFFIXES]
    tests = [path for path in files if _is_test(path)]
    lines = [f"Fix this bug: {subject}", ""]
    if sources:
        lines.append(f"The implementation to change: {', '.join(sources)}")
    if tests:
        lines.append(f"The failing test: {', '.join(tests)}")
    lines.append(f"Run the suite with: {command}")
    return "\n".join(lines)


def _first_task(repo: Path, history: int) -> RepoTask | None:
    try:
        commits = _git(repo, "log", f"--max-count={history}", "--format=%H%x00%s")
    except subprocess.CalledProcessError:
        return None
    for row in commits.splitlines():
        sha, _, subject = row.partition("\0")
        if any(word in subject.lower() for word in FIX_WORDS):
            task = _task_for(repo, sha, subject)
            if task:
                return task
    return None


def discover_tasks(limit: int = 3, history: int = 500) -> tuple[RepoTask, ...]:
    """Return runnable fixes from distinct repositories, newest candidates first."""
    tasks: list[RepoTask] = []
    repos = (repo for repo in sorted(REPOS.iterdir()) if repo.is_dir() and repo.name in COMMANDS)
    for repo in repos:
        task = _first_task(repo, history)
        if task:
            tasks.append(task)
        if len(tasks) == limit:
            break
    return tuple(tasks)
