"""Adapter definitions and output parsers.

An adapter describes how to invoke one external tool and how to read its output.
The argv is part of the adapter, **never** taken from project configuration:
`.aegisflow.json` is a repo-committed file, so letting it specify commands would
mean cloning a repository and running a hook executes whatever it says. Config
may enable a curated adapter and set its severity; it may not name a command.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

FAST = "fast"
SLOW = "slow"

#: path:line:col: message — the common "GNU" diagnostic form.
_GNU = re.compile(r"^(?P<path>[^:\n]+):(?P<line>\d+):(?:(?P<col>\d+):)?\s*(?P<message>.+)$")


@dataclass(frozen=True)
class LintFinding:
    """One diagnostic from an external tool."""

    tool: str
    code: str
    message: str
    line: int = 1
    column: int = 0
    fixable: bool = False


@dataclass(frozen=True)
class Adapter:
    """How to run one tool against one file, and how to read what it says."""

    name: str
    description: str
    suffixes: tuple[str, ...]
    argv: tuple[str, ...]
    parser: str
    cost: str = FAST
    version_argv: tuple[str, ...] = ()
    fix_hint: str = ""
    ok_exit_codes: tuple[int, ...] = (0,)

    def handles(self, path: str) -> bool:
        return path.endswith(self.suffixes)

    def command(self, target: str) -> list[str]:
        """Concrete argv for ``target``. ``{path}`` is the only substitution."""
        return [part.replace("{path}", target) for part in self.argv]

    def parse(self, stdout: str, stderr: str, exit_code: int) -> tuple[LintFinding, ...]:
        return PARSERS[self.parser](self, stdout, stderr, exit_code)


# ------------------------------------------------------------------- parsers


def _parse_ruff_json(adapter: Adapter, stdout: str, stderr: str, code: int):
    del stderr, code
    try:
        entries = json.loads(stdout or "[]")
    except json.JSONDecodeError:
        return ()
    findings = []
    for entry in entries:
        location = entry.get("location") or {}
        findings.append(
            LintFinding(
                tool=adapter.name,
                code=entry.get("code") or "ruff",
                message=entry.get("message", "").strip(),
                line=int(location.get("row", 1) or 1),
                column=int(location.get("column", 0) or 0),
                fixable=bool(entry.get("fix")),
            )
        )
    return tuple(findings)


def _parse_sarif(adapter: Adapter, stdout: str, stderr: str, code: int):
    """SARIF 2.1.0 — supported by most modern analysers, so one parser covers many."""
    del stderr, code
    try:
        document = json.loads(stdout or "{}")
    except json.JSONDecodeError:
        return ()
    findings = []
    for run in document.get("runs", []):
        for result in run.get("results", []):
            locations = result.get("locations") or [{}]
            region = (
                locations[0].get("physicalLocation", {}).get("region", {})
                if locations else {}
            )
            findings.append(
                LintFinding(
                    tool=adapter.name,
                    code=str(result.get("ruleId") or adapter.name),
                    message=str((result.get("message") or {}).get("text", "")).strip(),
                    line=int(region.get("startLine", 1) or 1),
                    column=int(region.get("startColumn", 0) or 0),
                )
            )
    return tuple(findings)


def _parse_gnu(adapter: Adapter, stdout: str, stderr: str, code: int):
    del code
    findings = []
    for line in (stdout + "\n" + stderr).splitlines():
        match = _GNU.match(line.strip())
        if not match:
            continue
        findings.append(
            LintFinding(
                tool=adapter.name,
                code=adapter.name,
                message=match.group("message").strip(),
                line=int(match.group("line")),
                column=int(match.group("col") or 0),
            )
        )
    return tuple(findings)


def _parse_presence(adapter: Adapter, stdout: str, stderr: str, code: int):
    """For check-only formatters that signal 'would reformat' by exit status."""
    if code in adapter.ok_exit_codes:
        return ()
    detail = (stdout.strip() or stderr.strip() or "formatting differs from the project style")
    return (
        LintFinding(
            tool=adapter.name,
            code=f"{adapter.name}.format",
            message=detail.splitlines()[0][:200],
            fixable=True,
        ),
    )


PARSERS = {
    "ruff_json": _parse_ruff_json,
    "sarif": _parse_sarif,
    "gnu": _parse_gnu,
    "presence": _parse_presence,
}
