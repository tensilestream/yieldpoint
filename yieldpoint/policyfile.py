"""Where this project's policy lives, and making sure it lives somewhere.

A field review recorded the failure this module exists to prevent: a block
message that said "change it in `.yieldpoint.json`" in a repository where no
such file existed. The reviewer could not see which rules were on, or what the
thresholds were, or that a limit was being enforced at all — the number came
from a default compiled into the tool.

The cause is that installing the hook and writing the config were separate
actions, and people only ever do the first: installing the hook is the step
that makes the tool *do* something. So enforcement began in repositories that
had never been told what they were enforcing, and the person being blocked was
by construction the one person who did not know a config was an option.

Hence the rule this module enforces:

    No entry point may begin enforcing until the thing it enforces is written
    down somewhere the person being stopped can open.

Writing it is best-effort, never fatal. Refusing to install because a file
cannot be written trades a visible problem for a worse one — and enforcing
silently on invisible defaults is the original defect.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .starter import STARTER_CONFIG

FILENAME = ".yieldpoint.json"


@dataclass(frozen=True)
class Written:
    """What happened when a policy file was asked for."""

    path: Path
    created: bool = False
    error: str = ""

    @property
    def visible(self) -> bool:
        """Whether a person can now open a file and read the rules in force."""
        return not self.error

    def describe(self) -> str:
        if self.error:
            return (f"could not write {self.path} ({self.error}); running on "
                    "built-in defaults, which no file in this repository states")
        return (f"wrote {self.path}" if self.created
                else f"{self.path} already exists, left alone")


def locate(root: str | Path = ".") -> Path | None:
    """The policy file in force here, or nothing if there is none."""
    path = Path(root) / FILENAME
    return path if path.is_file() else None


def ensure(root: str | Path = ".") -> Written:
    """Write the starter policy unless one is already there. Never raises.

    Never overwrites. A config that exists is a decision somebody made, and an
    installer that edits it is an installer people stop running.
    """
    path = Path(root) / FILENAME
    if path.is_file():
        return Written(path, created=False)
    try:
        path.write_text(json.dumps(STARTER_CONFIG, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        return Written(path, created=False, error=str(exc))
    return Written(path, created=True)


def where(root: str | Path = ".") -> str:
    """How to change a rule, naming only a path that actually resolves.

    Derived at the moment a finding is printed rather than written into the
    message, because the message outlives any one repository: an install from
    an older build, a deleted config or a policy a directory up all produce the
    same broken instruction otherwise.
    """
    found = locate(root)
    if found is not None:
        return f"change it in {found}"
    return (f"run `yieldpoint init` to write {FILENAME}, which states every "
            "rule and limit in force, and change it there")


__all__ = ["FILENAME", "Written", "ensure", "locate", "where"]
