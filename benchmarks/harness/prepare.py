"""Install the host tools required by the tasks selected for a harness run."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from collections.abc import Iterable

from repo_tasks import RepoTask, discover_tasks


FORMULAS = {
    "npm": "node", "cargo": "rust", "go": "go", "mvn": "maven", "bundle": "ruby",
}


def _tool(task: RepoTask) -> str:
    return task.test_command.split(maxsplit=1)[0]


def required(tasks: Iterable[RepoTask]) -> tuple[str, ...]:
    return tuple(sorted({_tool(task) for task in tasks if _tool(task) in FORMULAS}))


def _brew_install(formula: str) -> None:
    brew = shutil.which("brew")
    if not brew:
        raise RuntimeError(f"{formula} is required but Homebrew is unavailable; install it manually.")
    result = subprocess.run((brew, "install", formula), text=True, check=False)
    if result.returncode:
        raise RuntimeError(f"could not install {formula} with Homebrew")


def ensure_host_tools(tasks: Iterable[RepoTask], *, install: bool = True) -> tuple[str, ...]:
    """Return missing commands, installing their Homebrew formula when allowed."""
    missing = tuple(tool for tool in required(tasks) if not shutil.which(tool))
    if not install:
        return missing
    for tool in missing:
        _brew_install(FORMULAS[tool])
    unresolved = tuple(tool for tool in missing if not shutil.which(tool))
    if unresolved:
        raise RuntimeError(f"still missing after setup: {', '.join(unresolved)}")
    return missing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="report requirements without installing")
    args = parser.parse_args()
    tasks = discover_tasks()
    if len(tasks) != 3:
        print(f"prepare: needed three tasks, found {len(tasks)}", file=sys.stderr)
        return 2
    try:
        missing = ensure_host_tools(tasks, install=not args.check)
    except RuntimeError as exc:
        print(f"prepare: {exc}", file=sys.stderr)
        return 2
    action = "would install" if args.check else "installed"
    print(f"prepare: {action} {', '.join(missing) or 'nothing'}")
    print("Checkout dependencies are installed automatically before each benchmark arm.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
