"""Is this actually working?

Every check here exists because its absence produces the same symptom: nothing
happens, and nothing says why. A hook registered against a command that is not
on the editor's PATH, a config key spelled wrongly, a protected-test pattern
that matches no file — each leaves a tool that appears installed, reports
success, and verifies nothing.

That failure is worse than an outage. An outage is noticed.

Nothing here changes anything. It reads configuration, asks whether files
exist, and says what it found.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .core.policy import CONFIG_FILENAME, Policy

OK, WARN, FAIL = "ok", "warn", "fail"


@dataclass(frozen=True)
class Check:
    name: str
    state: str
    detail: str
    fix: str = ""

    @property
    def mark(self) -> str:
        return {OK: "ok  ", WARN: "warn", FAIL: "FAIL"}[self.state]


def run(root: str | Path = ".") -> list[Check]:
    """Every check, in the order someone would want to read them."""
    base = Path(root)
    policy = _policy(base)
    return [
        _command(),
        _git(),
        _config(base, policy),
        _protected(base, policy),
        _escalate_paths(base, policy),
        _hook(base),
        _mcp(base),
        _metrics(base, policy),
    ]


def _policy(base: Path) -> Policy:
    found = Policy.discover(base)
    return Policy.load(found) if found else Policy()


def _command() -> Check:
    """The command an editor will try to run, not the one you typed."""
    found = shutil.which("yieldpoint")
    if found:
        return Check("command", OK, f"yieldpoint on PATH at {found}")
    return Check(
        "command", WARN,
        "yieldpoint is not on PATH; editors launched from a desktop icon will "
        "not find it",
        "pip install yieldpoint, or let `yieldpoint init` register the "
        "interpreter path instead",
    )


def _git() -> Check:
    if shutil.which("git"):
        return Check("git", OK, "available; review and backtest will work")
    return Check("git", WARN, "git not found — `review` and `backtest` cannot run",
                 "install git, or use `yieldpoint check --diff -`")


def _config(base: Path, policy: Policy) -> Check:
    found = Policy.discover(base)
    if not found:
        return Check("config", WARN, f"no {CONFIG_FILENAME}; built-in defaults are in use",
                     "yieldpoint init")
    if policy.warnings:
        return Check(
            "config", FAIL,
            f"{len(policy.warnings)} problem(s) in {found}: " + "; ".join(policy.warnings),
            "fix the keys named above — the settings they carry are not in force",
        )
    return Check("config", OK, f"{found} loaded with no warnings")


def _protected(base: Path, policy: Policy) -> Check:
    """The check most worth having: does anything match the test patterns?

    If they match nothing, assertion monotonicity never runs and the product's
    central guarantee is quietly absent while everything reports success.
    """
    patterns = policy.test_contract.protected_patterns
    matched = _count_matching(base, lambda rel: policy.protects(rel))
    if matched:
        return Check("protected tests", OK,
                     f"{matched} file(s) match {len(patterns)} pattern(s)")
    return Check(
        "protected tests", FAIL,
        "no file in this repository matches any protected-test pattern, so "
        "assertion monotonicity will never run",
        f"set test_contract.protected_patterns in {CONFIG_FILENAME} to match "
        "your test files",
    )


def _escalate_paths(base: Path, policy: Policy) -> Check:
    from .scan import unmatched_patterns

    patterns = policy.routing.escalate_paths
    if not patterns:
        return Check("escalate paths", OK,
                     "none configured; importance comes from the import graph")
    dead = unmatched_patterns(base, patterns)
    if not dead:
        return Check("escalate paths", OK, f"{len(patterns)} pattern(s), all matching")
    return Check(
        "escalate paths", WARN,
        f"{len(dead)} pattern(s) match nothing: {', '.join(dead)}",
        "a path list that has stopped matching protects nothing; correct or "
        "remove these",
    )


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

    seen = sum(1 for e in ledger.load(ledger.path_for(resolved, base))
               if e.surface == "hook")
    if seen:
        return Check("hook", OK, f"running ({mode}); {seen:,} edit(s) seen")
    return Check(
        "hook", WARN,
        f"installed and runnable ({mode}), but it has never seen an edit",
        "hooks are read when a session starts — restart your editor, or start "
        "a new session. Until then use `yieldpoint review` before committing.",
    )


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


def _metrics(base: Path, policy: Policy) -> Check:
    from . import ledger

    if os.environ.get("YIELDPOINT_NO_METRICS"):
        return Check("metrics", OK, "disabled by YIELDPOINT_NO_METRICS")
    if ledger.under_test():
        return Check("metrics", OK, "not recording: this is a test run, so the "
                                    "numbers stay yours")
    if not policy.metrics.enabled:
        return Check("metrics", OK, "disabled in policy")
    ledger = base / policy.metrics.path
    if not ledger.exists():
        return Check("metrics", OK, "enabled; nothing recorded yet")
    lines = sum(1 for _ in ledger.open(encoding="utf-8", errors="ignore"))
    return Check("metrics", OK, f"{lines:,} verdict(s) recorded in {ledger}")


def _runs(command: str) -> bool:
    """Does the registered command actually start? Asked, not assumed."""
    import shlex

    parts = shlex.split(command)
    if not parts:
        return False
    if parts[0] != "yieldpoint" and not Path(parts[0]).exists():
        return False
    try:
        completed = subprocess.run(
            [parts[0], "--version"], capture_output=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def _count_matching(base: Path, predicate) -> int:
    count = 0
    for path in base.rglob("*"):
        if not path.is_file():
            continue
        relative = str(path.relative_to(base))
        if ".git/" in relative or relative.startswith(".git"):
            continue
        if predicate(relative):
            count += 1
    return count


def render(checks: list[Check]) -> str:
    lines = ["Yieldpoint doctor", ""]
    for check in checks:
        lines.append(f"  [{check.mark}] {check.name:<16} {check.detail}")
        if check.fix and check.state != OK:
            lines.append(f"         {'':<16} -> {check.fix}")
    failures = sum(1 for c in checks if c.state == FAIL)
    warnings = sum(1 for c in checks if c.state == WARN)
    lines.append("")
    if failures:
        lines.append(f"  {failures} problem(s) mean Yieldpoint is not doing what you "
                     "think it is.")
    elif warnings:
        lines.append(f"  Working, with {warnings} thing(s) not switched on.")
    else:
        lines.append("  Everything checked is in order.")
    return "\n".join(lines)


def worst(checks: list[Check]) -> str:
    if any(c.state == FAIL for c in checks):
        return FAIL
    return WARN if any(c.state == WARN for c in checks) else OK


__all__ = ["Check", "run", "render", "worst", "OK", "WARN", "FAIL"]
