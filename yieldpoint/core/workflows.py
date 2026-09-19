"""Integrity of the checks themselves.

"The agent made the tests pass by weakening the tests" has a sibling one layer
up: **the agent made CI pass by weakening CI.** Deleting a job, appending
`|| true` to a command, adding `continue-on-error: true`, or gating a step behind
`if: false` all turn a green build into a meaningless one, and none of it touches
a single assertion.

Continuous-integration definitions are YAML, and the verification core takes no
runtime dependencies — so this analysis is lexical rather than a real parse, and
its findings are marked :attr:`Confidence.LEXICAL`, which the verdict contract
**structurally prevents from blocking**. It is a warning that a human should look,
never a gate that stops work on a guess.

Identity is the command text with neutering suffixes stripped, so a step that
gains `|| true` is recognised as the *same* step, disabled — not as one step
removed and a different one added.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .verdict import Confidence, Finding

CI_CHECK_REMOVED = "ci_check_removed"
CI_CHECK_DISABLED = "ci_check_disabled"

#: Files whose job is to run other checks.
WORKFLOW_PATTERNS = (
    "**/.github/workflows/*.yml", "**/.github/workflows/*.yaml",
    ".github/workflows/*.yml", ".github/workflows/*.yaml",
    "**/.pre-commit-config.yaml", ".pre-commit-config.yaml",
    "**/.gitlab-ci.yml", ".gitlab-ci.yml",
)

_STEP = re.compile(r"^(?P<indent>\s*)-\s+(?P<rest>\S.*)$")
_KEY = re.compile(r"^(?P<indent>\s*)(?P<key>[A-Za-z_][\w-]*)\s*:\s*(?P<value>.*)$")
_SUPPRESSED = re.compile(r"(\|\|\s*(true|:)\s*$)|(;\s*true\s*$)|(^-\s)", re.M)
_FALSE_IF = re.compile(r"^\s*(false|\$\{\{\s*false\s*\}\})\s*$", re.I)


@dataclass(frozen=True)
class Step:
    """One thing CI does, and whether its failure still matters."""

    identity: str
    line: int
    disabled: str | None = None


def steps_of(source: str) -> tuple[Step, ...]:
    """Extract the commands and actions a workflow runs."""
    lines = source.splitlines()
    steps: list[Step] = []
    blocks = _blocks(lines)

    for start, end, indent in blocks:
        body = lines[start:end]
        identity = _identity(body)
        if not identity:
            continue
        steps.append(Step(identity, start + 1, _disabled(body, indent, lines, start)))
    return tuple(steps)


def check(
    before: str | None, after: str | None, path: str, config
) -> tuple[list[Finding], list[str]]:
    """Report checks this change removed or disabled."""
    if after is None:
        return [], []
    removed_status = getattr(config, "check_removed", None)
    disabled_status = getattr(config, "check_disabled", None)
    if removed_status is None and disabled_status is None:
        return [], []

    now = {step.identity: step for step in steps_of(after)}
    was = {step.identity: step for step in steps_of(before or "")}

    findings: list[Finding] = []
    for identity, step in (was.items() if removed_status else ()):
        if identity in now:
            continue
        findings.append(_finding(
            CI_CHECK_REMOVED, removed_status, path, step.line,
            f"CI no longer runs `{_short(identity)}`.",
            "Restore the step. If the check is genuinely obsolete, remove it in a "
            "change that says so — a build that stops running a check still reports "
            "green.",
        ))

    for identity, step in (now.items() if disabled_status else ()):
        previous = was.get(identity)
        if not step.disabled or (previous is not None and previous.disabled):
            continue
        findings.append(_finding(
            CI_CHECK_DISABLED, disabled_status, path, step.line,
            f"`{_short(identity)}` can no longer fail the build ({step.disabled}).",
            "Remove the suppression and fix the underlying failure. A step that "
            "cannot fail is a step that is not running.",
        ))
    return sorted(findings, key=lambda f: (f.line, f.rule)), []


def _blocks(lines: list[str]) -> list[tuple[int, int, int]]:
    """Locate each `- ` list item and the extent of its body."""
    starts: list[tuple[int, int]] = []
    for index, line in enumerate(lines):
        match = _STEP.match(line)
        if match:
            starts.append((index, len(match.group("indent"))))

    blocks = []
    for position, (index, indent) in enumerate(starts):
        end = len(lines)

        # A step ends at its next sibling...
        for later_index, later_indent in starts[position + 1:]:
            if later_indent <= indent:
                end = later_index
                break

        # ...or wherever the document dedents out of the list, whichever comes
        # first. Without the dedent check a step swallows the following job, and
        # that job's `continue-on-error` is read as this step's.
        for later_index in range(index + 1, end):
            line = lines[later_index]
            if not line.strip() or line.strip().startswith("#"):
                continue
            if len(line) - len(line.lstrip()) < indent:
                end = later_index
                break

        blocks.append((index, end, indent))
    return blocks


def _identity(body: list[str]) -> str:
    """What this step actually does: its action, or its command."""
    for line in body:
        match = _KEY.match(line.lstrip("- "))
        if match and match.group("key") in ("uses", "repo"):
            value = match.group("value").strip()
            if value:
                return f"uses:{value}"

    command = _command(body)
    return f"run:{_normalise(command)}" if command else ""


def _command(body: list[str]) -> str:
    """The `run:` value, including block scalars."""
    for index, line in enumerate(body):
        stripped = line.lstrip("- ")
        match = _KEY.match(stripped)
        if not match or match.group("key") != "run":
            continue
        value = match.group("value").strip()
        if value not in ("|", ">", "|-", ">-", ""):
            return value
        collected = []
        for following in body[index + 1:]:
            if following.strip() and not following.startswith(" " * (len(line) - len(line.lstrip()) + 2)):
                break
            collected.append(following.strip())
        return " ".join(part for part in collected if part)
    return ""


def _normalise(command: str) -> str:
    """Strip suppression so a disabled step keeps the identity it had."""
    text = re.sub(r"\s+", " ", command).strip()
    text = re.sub(r"\s*\|\|\s*(true|:)\s*$", "", text)
    text = re.sub(r"\s*;\s*true\s*$", "", text)
    return text


def _disabled(body: list[str], indent: int, lines: list[str], start: int) -> str | None:
    """Why this step's failure no longer matters, if it does not."""
    for line in body:
        match = _KEY.match(line.lstrip("- "))
        if not match:
            continue
        key, value = match.group("key"), match.group("value").strip()
        if key == "continue-on-error" and value.lower() in ("true", "'true'", '"true"'):
            return "continue-on-error: true"
        if key == "if" and _FALSE_IF.match(value):
            return f"if: {value}"

    command = _command(body)
    if command and re.search(r"(\|\|\s*(true|:)|;\s*true)\s*$", command):
        return "suppressed with `|| true`"

    return _job_disabled(lines, start, indent)


def _job_disabled(lines: list[str], start: int, indent: int) -> str | None:
    """A job-level suppression disables every step inside it."""
    for index in range(start - 1, -1, -1):
        line = lines[index]
        if not line.strip() or line.strip().startswith("#"):
            continue
        match = _KEY.match(line)
        if not match:
            continue
        current = len(match.group("indent"))
        if current >= indent:
            continue
        key, value = match.group("key"), match.group("value").strip()
        if key == "continue-on-error" and value.lower().strip("'\"") == "true":
            return "the job sets continue-on-error: true"
        if key == "if" and _FALSE_IF.match(value):
            return f"the job is gated on {value}"
        if current == 0:
            break
    return None


def _short(identity: str) -> str:
    text = identity.split(":", 1)[1] if ":" in identity else identity
    return text if len(text) <= 70 else f"{text[:67]}..."


def _finding(rule, status, path, line, detail, prescription) -> Finding:
    return Finding(
        rule=rule, status=status, file=path, line=line, detail=detail,
        prescription=prescription, confidence=Confidence.LEXICAL,
    )
