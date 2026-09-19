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
    from .doctorwiring import _git_gate, _hook, _mcp, _stop_gate

    base = Path(root)
    policy = _policy(base)
    return [
        _command(),
        _git(),
        _config(base, policy),
        _protected(base, policy),
        _escalate_paths(base, policy),
        _hook(base),
        _stop_gate(base),
        _git_gate(base),
        _mcp(base),
        _metrics(base, policy),
    ]


def _policy(base: Path) -> Policy:
    found = Policy.discover(base)
    return Policy.load(found) if found else Policy()


def _command() -> Check:
    """The command an editor will try to run, not the one you typed.

    On PATH is not the same as runnable. An editable install whose source
    directory has since moved leaves the console script behind and takes the
    package with it, and a check that stopped at :func:`shutil.which` would
    call that healthy — on the very line a reader looks at first to find out
    why nothing works. So it is asked, the same way the hook is.
    """
    import shlex

    found = shutil.which("yieldpoint")
    if not found:
        return Check(
            "command", WARN,
            "yieldpoint is not on PATH; editors launched from a desktop icon will "
            "not find it",
            "pip install yieldpoint, or let `yieldpoint init` register the "
            "interpreter path instead",
        )
    if not _runs(shlex.quote(found)):
        return Check(
            "command", FAIL, f"{found} is on PATH but does not run",
            "the install is broken rather than missing — most often an editable "
            "install whose source directory has moved. Reinstall it from the "
            "current checkout: pip install -e .",
        )
    return Check("command", OK, f"yieldpoint on PATH at {found}")


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
