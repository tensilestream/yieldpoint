"""Files this piece of work said it would not touch.

The one thing in the field review that neither baselining nor better wording
fixes. The instruction — *"don't touch anything else"* — existed, was followed,
and was invisible to every tool in the loop.

This is the only rule here that knows something the code cannot tell it. Every
other rule reads the source and reaches a conclusion; this one compares what
changed against what somebody said would change, which is information that has
to be declared or it does not exist.

Reported, never blocking. A scope is a statement of intent and intent changes
mid-task for good reasons — discovering the fix belongs one layer down is
normal work, not misconduct. What must not happen is the drift going unnoticed
until a review, which is exactly when it is most expensive to unwind.
"""

from __future__ import annotations

from .verdict import Confidence, Finding, Status

OUT_OF_SCOPE_EDIT = "out_of_scope_edit"
NEW_FILE_OUT_OF_SCOPE = "new_file_out_of_scope"


def _finding(rule: str, path: str, detail: str, fix: str, severity: Status) -> Finding:
    return Finding(rule=rule, status=severity, file=path, line=1, detail=detail,
                   prescription=fix, confidence=Confidence.EXACT)


def check(task, changed, created=(), severity: Status | None = Status.REPAIR):
    """Report changes outside what this task declared.

    ``changed`` is every path the change touched; ``created`` those it added.
    An undeclared task reports nothing — silence is not a scope of zero files.
    """
    if severity is None or task is None or not task.declared:
        return []

    findings = []
    surface = ", ".join(task.touch) if task.touch else "nothing in particular"
    for path in sorted(set(changed)):
        if task.covers(path):
            continue
        findings.append(_finding(
            OUT_OF_SCOPE_EDIT, path,
            f"{path} is outside what this task said it would touch ({surface}).",
            "If the work genuinely needs it, widen the task with `yieldpoint "
            "task --touch`. If not, this change has drifted from what was "
            "asked, and the sooner that is unwound the cheaper it is.",
            severity))

    if task.no_new_files:
        findings.extend(_finding(
            NEW_FILE_OUT_OF_SCOPE, path,
            f"{path} is a new file, and this task said it would add none.",
            "Put it where the existing code lives, or clear the constraint "
            "with `yieldpoint task` if a new file is genuinely the right shape.",
            severity) for path in sorted(set(created)) if not task.covers(path))
    return findings


__all__ = ["OUT_OF_SCOPE_EDIT", "NEW_FILE_OUT_OF_SCOPE", "check"]
