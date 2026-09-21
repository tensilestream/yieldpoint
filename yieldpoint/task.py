"""What this piece of work was supposed to touch.

The sharpest thing in the field review, filed under a speculative daemon
proposal where it would have been missed:

    *"You said 'don't touch anything else', and nothing in the toolchain knew
    that — the hook happily blocked me on files that instruction excluded."*

Every other failure that session was about attribution: the tool could not tell
debt the change created from debt it inherited. This one is different and
neither baselining nor better messages fix it. The instruction existed, the
person followed it, and the toolchain had no way to hear it. So it blocked them
on files they had been told to leave alone, and the only way through was to
edit one of them.

A declared scope is the missing half. Baselining answers *did you make it
worse*; this answers *were you supposed to be here at all*. They compose: a
finding that is both inherited and out of scope is not this change's business
twice over.

Agent-agnostic without a daemon. It is a file and an exit code, so anything
that can run a command participates — which is every agent, and every human.

Uncommitted on purpose. A task is one person's current piece of work, not a
property of the repository, and committing it would mean every clone inherits
somebody else's instructions.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .core import glob

#: Beside the ledger, in the directory this tool already owns and git ignores.
LOCATION = ".yieldpoint/task.json"


@dataclass(frozen=True)
class Task:
    """The surface a piece of work declared for itself."""

    description: str = ""
    touch: tuple[str, ...] = field(default_factory=tuple)
    """Globs this work is allowed to change. Empty means no scope was declared,
    which is not the same as a scope of nothing."""

    no_new_files: bool = False
    no_grow: bool = False

    @property
    def declared(self) -> bool:
        """Whether anything was actually said. An undeclared task constrains
        nothing — silence must not read as a scope of zero files."""
        return bool(self.touch or self.no_new_files or self.no_grow)

    def covers(self, path: str) -> bool:
        """Whether this path is inside the declared surface.

        True when nothing was declared: without a contract every file is in
        scope, which is how the tool behaved before this existed.
        """
        if not self.touch:
            return True
        return glob.matches_any(self.touch, path.replace("\\", "/"))

    def to_dict(self) -> dict:
        return {"description": self.description, "touch": list(self.touch),
                "no_new_files": self.no_new_files, "no_grow": self.no_grow}


def _path(root: str | Path) -> Path:
    return Path(root) / LOCATION


def load(root: str | Path = ".") -> Task:
    """The task in force, or an empty one. Never raises.

    A corrupt or unreadable task file must not stop a verification: the rules
    are what matter and a scope is an extra.
    """
    try:
        raw = json.loads(_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return Task()
    if not isinstance(raw, dict):
        return Task()
    return Task(
        description=str(raw.get("description", "")),
        touch=tuple(str(g) for g in raw.get("touch", ()) if isinstance(g, str)),
        no_new_files=bool(raw.get("no_new_files", False)),
        no_grow=bool(raw.get("no_grow", False)),
    )


def save(task: Task, root: str | Path = ".") -> Path:
    target = _path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(task.to_dict(), indent=2) + "\n", encoding="utf-8")
    return target


def clear(root: str | Path = ".") -> bool:
    """Forget the declared scope. True when there was one."""
    target = _path(root)
    if not target.is_file():
        return False
    target.unlink()
    return True


__all__ = ["Task", "LOCATION", "load", "save", "clear", "task_command",
           "add_command"]


def _show(task: Task, root) -> str:
    if not task.declared:
        return ("No task scope declared. Every file is in scope, which is how "
                "this behaves without one.")
    lines = [f"Task: {task.description}" if task.description else "Task scope"]
    lines.append(f"  may touch: {', '.join(task.touch) if task.touch else 'anything'}")
    if task.no_new_files:
        lines.append("  no new files")
    if task.no_grow:
        lines.append("  no file may grow")
    lines.append("  Reported, never enforced — drift is worth seeing, not refusing.")
    lines.append(f"  Clear it with `yieldpoint task --clear`. Not committed: a task "
                 f"is your current work, not the repository's.")
    return "\n".join(lines)


def _globs(values) -> tuple[str, ...]:
    """Repeated flags and comma-separated lists, which people mix freely."""
    return tuple(g.strip() for value in (values or [])
                 for g in value.split(",") if g.strip())


def _declares(args) -> bool:
    return bool(args.description or args.touch or args.no_new_files or args.no_grow)


def task_command(args) -> int:
    import sys

    if args.clear:
        print("Task scope cleared." if clear(args.root) else "No task scope was set.")
        return 0
    if not _declares(args):
        print(_show(load(args.root), args.root))
        return 0

    task = Task(description=args.description or "", touch=_globs(args.touch),
                no_new_files=bool(args.no_new_files), no_grow=bool(args.no_grow))
    try:
        save(task, args.root)
    except OSError as exc:
        print(f"yieldpoint: {exc}", file=sys.stderr)
        return 2
    print(_show(task, args.root))
    return 0


def add_command(sub) -> None:
    command = sub.add_parser(
        "task", help="declare what this piece of work is allowed to touch")
    command.add_argument("description", nargs="?", default="",
                         help="what the work is, in a few words")
    command.add_argument("--touch", action="append",
                         help="glob this work may change; repeatable or comma-separated")
    command.add_argument("--no-new-files", action="store_true")
    command.add_argument("--no-grow", action="store_true")
    command.add_argument("--clear", action="store_true", help="forget the scope")
    command.add_argument("--root", default=".")
    command.set_defaults(handler=task_command)
