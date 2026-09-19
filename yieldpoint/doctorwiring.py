"""Is Yieldpoint wired into the things that call it?

Split from ``doctor.py`` because these checks answer a different question. The
rest of the doctor asks whether this project is configured; these ask whether
any of it is reachable from the tools doing the work — and that has three
separate answers, because there are three doors and each one is blind to a case
the others catch:

* the **per-edit hook** verifies a tool call, so it sees only edits made with
  tools whose payload can be replayed;
* the **Stop gate** asks git instead, so it sees edits made through the shell —
  which the per-edit hook structurally cannot;
* the **pre-commit gate** holds for providers with no editor hooks at all.

Each is reported on its own line. Folding them into one "hooks: ok" would hide
exactly the case this module exists to surface: a gate that is installed,
runnable, and never reached.
"""

from __future__ import annotations

from pathlib import Path

from .core.policy import Policy
from .doctor import Check, FAIL, OK, WARN, _runs


def _hook(base: Path) -> Check:
    settings = base / ".claude" / "settings.json"
    if not settings.is_file():
        return Check("hook", WARN, "not installed; nothing is enforcing",
                     "yieldpoint init  (or yieldpoint install-hook)")
    import json

    try:
        data = json.loads(settings.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return Check("hook", FAIL, f"{settings} is unreadable: {exc}")

    entries = [
        hook.get("command", "")
        for entry in data.get("hooks", {}).get("PreToolUse", [])
        for hook in entry.get("hooks", [])
        if "yieldpoint" in str(hook.get("command", ""))
    ]
    if not entries:
        return Check("hook", WARN, f"{settings} has no Yieldpoint PreToolUse hook",
                     "yieldpoint install-hook")
    command = entries[0]
    if not _runs(command):
        return Check("hook", FAIL, f"registered command does not run: {command}",
                     "yieldpoint install-hook  (it will register a command that resolves)")
    mode = "advisory — reports, never blocks" if "--advisory" in command else "enforcing"
    return _fired(base, mode)


def _fired(base: Path, mode: str) -> Check:
    """Installed is not the same as running.

    A hook is read when a session starts, so one installed mid-session does
    nothing until the next one — and the symptom is indistinguishable from
    working: no output, no error, every edit allowed. This is the check that
    tells the two apart, by asking whether the hook has ever recorded a verdict.
    """
    from . import ledger
    from .core.policy import Policy

    policy = Policy.discover(base)
    resolved = Policy.load(policy) if policy else Policy()
    if not ledger.enabled(resolved):
        return Check("hook", OK, f"installed and runnable ({mode}); "
                                 "recording is off, so it cannot be confirmed running")

    events = list(ledger.load(ledger.path_for(resolved, base)))
    seen = sum(1 for e in events if e.surface == "hook")
    if seen:
        return Check("hook", OK, f"running ({mode}); {seen:,} edit(s) seen")

    # Never fired, but the turn-level gate has: the agent is editing through
    # something this hook cannot see — a shell command, most often. That is a
    # real and common configuration, not a broken install, and saying "restart
    # your editor" to someone whose editor is fine wastes the hour.
    if any(e.surface == "stop" for e in events):
        # OK, not a warning: enforcement is intact, it is simply happening at
        # the other door. Flagging this amber sends someone to fix a config
        # that is already correct.
        return Check(
            "hook", OK,
            f"installed ({mode}) but never triggered — this agent edits through "
            "a tool it cannot replay, typically a shell command. The Stop gate "
            "covers those, and it is running.",
        )
    return Check(
        "hook", WARN,
        f"installed and runnable ({mode}), but it has never seen an edit",
        "hooks are read when a session starts — restart your editor, or start "
        "a new session. Until then use `yieldpoint review` before committing.",
    )


def _registered_on_stop(base: Path) -> tuple[str, Check | None]:
    """The Stop command Yieldpoint registered, or the Check explaining its absence."""
    settings = base / ".claude" / "settings.json"
    if not settings.is_file():
        return "", Check("stop gate", WARN,
                         "not installed; shell-written edits are not verified",
                         "yieldpoint install-hook")
    import json

    try:
        data = json.loads(settings.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return "", Check("stop gate", FAIL, f"{settings} is unreadable: {exc}")

    commands = [
        str(hook.get("command", ""))
        for entry in data.get("hooks", {}).get("Stop", [])
        for hook in entry.get("hooks", [])
    ]
    gate = next((c for c in commands if "yieldpoint" in c and "--stop" in c), "")
    if not gate:
        return "", Check(
            "stop gate", WARN,
            "no `yieldpoint hook --stop` on Stop; an edit made through the "
            "shell reaches no gate at all",
            "yieldpoint install-hook  (it registers the Stop gate too)",
        )
    return gate, None


def _stop_gate(base: Path) -> Check:
    """The gate that does not care which tool made the edit.

    Worth its own line because its absence is invisible: the per-edit hook above
    reports OK, the install looks complete, and every shell-written edit goes
    unverified.
    """
    gate, missing = _registered_on_stop(base)
    if missing is not None:
        return missing
    if not _runs(gate):
        return Check("stop gate", FAIL, f"registered command does not run: {gate}",
                     "yieldpoint install-hook")

    mode = "advisory — reports, never blocks" if "--advisory" in gate else "enforcing"
    seen = _turns_verified(base)
    if seen is None:
        return Check("stop gate", OK, f"installed and runnable ({mode})")
    if seen:
        return Check("stop gate", OK, f"running ({mode}); {seen:,} turn(s) verified")
    return Check(
        "stop gate", WARN,
        f"installed and runnable ({mode}), but it has never run",
        "hooks are read when a session starts — restart your editor, or start "
        "a new session.",
    )


def _turns_verified(base: Path) -> int | None:
    """Turns this gate has verified, or ``None`` when recording is off."""
    from . import ledger

    found = Policy.discover(base)
    resolved = Policy.load(found) if found else Policy()
    if not ledger.enabled(resolved):
        return None
    return sum(1 for e in ledger.load(ledger.path_for(resolved, base))
               if e.surface == "stop")


def _git_gate(base: Path) -> Check:
    """The door that holds for providers with no editor hook at all."""
    from .install import GIT_MARKER

    git = base / ".git"
    if git.is_file():
        try:
            git = Path(git.read_text(encoding="utf-8").split("gitdir:", 1)[1].strip())
        except (OSError, IndexError):
            return Check("git gate", WARN, "cannot resolve this worktree's git directory")
    if not git.is_dir():
        return Check("git gate", WARN, "not a git repository; commits cannot be gated")

    path = git / "hooks" / "pre-commit"
    if not path.is_file():
        return Check(
            "git gate", WARN,
            "no pre-commit gate; an agent with no editor hook is unverified",
            "yieldpoint init  (writes .git/hooks/pre-commit)",
        )
    text = path.read_text(encoding="utf-8", errors="replace")
    if GIT_MARKER not in text:
        if "yieldpoint" in text:
            return Check("git gate", OK, f"{path} runs yieldpoint (hand-written)")
        return Check(
            "git gate", WARN,
            f"{path} exists but does not run yieldpoint",
            "yieldpoint init  (it backs yours up before replacing it)",
        )
    import os

    if not os.access(path, os.X_OK):
        return Check("git gate", FAIL, f"{path} is not executable, so git skips it",
                     f"chmod +x {path}")
    return Check("git gate", OK, f"{path} verifies staged work on every commit")


def _mcp(base: Path) -> Check:
    config = base / ".mcp.json"
    if not config.is_file():
        return Check("mcp", WARN, "not registered for this project",
                     "yieldpoint install-mcp --client claude-code")
    import json

    try:
        data = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return Check("mcp", FAIL, f"{config} is unreadable: {exc}")
    entry = data.get("mcpServers", {}).get("yieldpoint")
    if not entry:
        return Check("mcp", WARN, f"{config} has no yieldpoint server",
                     "yieldpoint install-mcp --client claude-code")
    command = " ".join([entry.get("command", ""), *entry.get("args", [])])
    if not _runs(command):
        return Check("mcp", FAIL, f"registered command does not run: {command}",
                     "yieldpoint install-mcp --client claude-code")
    return Check("mcp", OK, "registered and runnable")
