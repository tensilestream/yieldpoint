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
    return ("/tests/" in lowered or "/test/" in lowered or "/spec/" in lowered or name.startswith("test_")
            or name.endswith(("_test.py", "_test.go", "spec.rb", ".spec.js", ".test.js")))


def _task_for(repo: Path, sha: str, subject: str) -> RepoTask | None:
    try:
        changed, files = _paths(repo, sha)
    except subprocess.CalledProcessError:
        return None
    suitable = changed < 200 and any(map(_is_test, files)) and not all(map(_is_test, files))
    if not suitable:
        return None
    return RepoTask(f"{repo.name}-{sha[:8]}", repo.name, sha,
                    f"Reproduce and fix this bug: {subject}", COMMANDS[repo.name], files)


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
