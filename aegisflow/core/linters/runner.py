"""Safe execution of external linters.

Two constraints shape this module.

The content being verified is usually *proposed* and not yet on disk — a hook
runs before the write. So the runner materialises the after-content into a
temporary file **in the target's own directory**, which keeps per-directory tool
configuration (``pyproject.toml``, ``.eslintrc``) applicable.

Nothing is ever run through a shell, and the argv comes from the curated
registry rather than from project configuration. A tool that is not installed is
reported as skipped, never as a pass.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .adapter import Adapter, LintFinding

PROJECT_SCOPED = "project-scoped tool cannot verify content that is not yet written"


@dataclass(frozen=True)
class LintResult:
    tool: str
    findings: tuple[LintFinding, ...] = ()
    skipped: str | None = None
    version: str = ""

    @property
    def ran(self) -> bool:
        return self.skipped is None


def run(adapter: Adapter, path: str, content: str, *, timeout: int = 10) -> LintResult:
    """Run one adapter against ``content``. Never raises."""
    if not any("{path}" in part for part in adapter.argv):
        # Tools that analyse a whole project (spotless, tsc, clippy) read what is
        # on disk, which is not what we are verifying. Saying so beats guessing.
        return LintResult(adapter.name, skipped=PROJECT_SCOPED)

    executable = shutil.which(adapter.argv[0])
    if executable is None:
        return LintResult(adapter.name, skipped=f"{adapter.argv[0]} is not installed")

    target = Path(path)
    directory = target.parent if target.parent.exists() else Path.cwd()
    handle = None
    try:
        handle = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=target.suffix,
            prefix=".aegisflow-", dir=directory, delete=False,
        )
        handle.write(content)
        handle.close()
        completed = subprocess.run(  # noqa: S603 - argv is curated, shell is never used
            adapter.command(handle.name),
            capture_output=True, text=True, timeout=timeout, check=False,
            cwd=str(directory), env={**os.environ, "NO_COLOR": "1"},
        )
    except subprocess.TimeoutExpired:
        return LintResult(adapter.name, skipped=f"timed out after {timeout}s")
    except (OSError, ValueError) as exc:
        return LintResult(adapter.name, skipped=f"could not run {adapter.name}: {exc}")
    finally:
        if handle is not None:
            Path(handle.name).unlink(missing_ok=True)

    findings = adapter.parse(completed.stdout, completed.stderr, completed.returncode)
    if not findings and completed.returncode not in adapter.ok_exit_codes:
        detail = (completed.stderr or completed.stdout).strip().splitlines()
        return LintResult(
            adapter.name,
            skipped=f"{adapter.name} exited {completed.returncode}: "
                    f"{detail[0][:160] if detail else 'no output'}",
        )
    return LintResult(adapter.name, findings=findings, version=version_of(adapter.version_argv))


@lru_cache(maxsize=64)
def version_of(version_argv: tuple[str, ...]) -> str:
    """Record the tool version, so a differing verdict elsewhere is explainable."""
    if not version_argv or shutil.which(version_argv[0]) is None:
        return ""
    try:
        completed = subprocess.run(  # noqa: S603 - curated argv, no shell
            list(version_argv), capture_output=True, text=True,
            timeout=5, check=False,
        )
    except (subprocess.SubprocessError, OSError):
        return ""
    return (completed.stdout or completed.stderr).strip().splitlines()[0][:80] if (
        completed.stdout or completed.stderr
    ) else ""
