"""The verification entry point.

``verify_change`` is the core primitive: given the before and after content of
one file, return a :class:`Verdict`. Everything else — the CLI, the Claude Code
hook, the LangGraph node, a future MCP server — is a translation layer over this
one call.

Policy decides severity; this module decides only whether a rule fired. A file
that cannot be analysed is recorded in ``skipped`` and never counted as passing
(RULES.md section 5).
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable, Mapping

from .core import contract as contractrules
from .core import diff as diffmod
from .core import generated as generatedmod
from .core import boundaries, monotonicity, refactor, structure
from .core.assertions import extract
from .core.contract import ASSERTION_MONOTONICITY, EXACT_SUFFIXES
from .core.linters import report as lintreport
from .core.policy import Policy
from .core.relation import Relation
from .core.verdict import Confidence, Finding, Status, Verdict

Reader = Callable[[str], "str | None"]

GENERATED_FILE_EDITED = "generated_file_edited"

__all__ = [
    "verify_change", "verify_diff",
    "ASSERTION_MONOTONICITY", "GENERATED_FILE_EDITED", "EXACT_SUFFIXES",
]


def verify_change(
    before: str | None,
    after: str | None,
    path: str,
    policy: Policy | str | dict | None = None,
    *,
    also_covered: Mapping[str, Relation] | None = None,
    also_defined: Iterable[str] = (),
    hand_edit: bool = False,
) -> Verdict:
    """Verify one file's transition from ``before`` to ``after``.

    ``before`` is ``None`` for a newly created file and ``after`` is ``None`` for
    a deleted one. ``also_covered`` carries subjects verified elsewhere in the
    same change set, so relocating a test is not reported as loss.

    ``hand_edit`` says this change is being composed right now rather than
    arriving as a committed diff, which is what distinguishes hand-editing a
    generated file from regenerating one.
    """
    resolved = Policy.load(policy)

    origin = _generated(before, after, path, resolved, hand_edit)
    if origin is not None:
        return origin

    findings: list[Finding] = []
    checked: list[str] = []
    skipped: list[str] = []

    lint_findings, lint_skipped = lintreport.collect(after, path, resolved)
    findings.extend(lint_findings)
    skipped.extend(lint_skipped)

    if path.endswith(EXACT_SUFFIXES):
        names, names_skipped = refactor.check(
            before, after, path,
            on_dangling=resolved.refactor.dangling_reference,
            on_export_removed=resolved.refactor.export_removed,
            also_defined=also_defined or (),
        )
        findings.extend(names)
        skipped.extend(names_skipped)

        shape, shape_skipped = structure.check(before, after, path, resolved.structure)
        findings.extend(shape)
        skipped.extend(shape_skipped)

        layers, layers_skipped = boundaries.check(before, after, path, resolved.boundaries)
        findings.extend(layers)
        skipped.extend(layers_skipped)
        if not names_skipped:
            checked.append(path)

    contract = contractrules.check(before, after, path, resolved, also_covered)
    findings.extend(contract.findings)
    checked.extend(c for c in contract.checked if c not in checked)
    skipped.extend(contract.skipped)

    if not checked and not skipped:
        checked.append(path)
    return Verdict.of(
        contractrules.deduplicate(findings), checked=checked, skipped=skipped
    )


def verify_diff(
    diff_text: str,
    root: str | Path = ".",
    policy: Policy | str | dict | None = None,
    *,
    read: Reader | None = None,
) -> Verdict:
    """Verify a whole change set given a unified diff.

    The after-state is read from ``root`` (or from ``read``) and the before-state
    is reconstructed by reverse-applying the diff, which is exact. A file whose
    diff does not line up is recorded as skipped rather than analysed against a
    reconstruction that may be wrong.

    Subjects are pooled across every changed file first, so moving a test from
    one file to another is not reported as lost verification.
    """
    resolved = Policy.load(policy)
    base = Path(root)
    fetch = read or (lambda rel: _read_file(base / rel))

    states, verdict = _collect(diffmod.parse(diff_text), fetch, resolved)
    covered = _pool(states, resolved)
    defined = _pool_definitions(states)

    for path, before, after in states:
        verdict = verdict.merge(
            verify_change(
                before, after, path, resolved,
                also_covered=covered, also_defined=defined,
            )
        )
    return verdict.merge(_change_size(states, resolved))


def _change_size(states, policy: Policy) -> Verdict:
    """Cap the size of the whole change, not only of each file.

    A change can stay under every per-file limit and still be unreviewable in
    aggregate — forty files of a hundred lines each is the shape an agent
    produces and a human approves without reading.
    """
    limit = policy.structure.max_change_lines
    if not limit or policy.structure.severity is None:
        return Verdict.of([])

    added = sum(
        len((after or "").splitlines()) - len((before or "").splitlines())
        for _path, before, after in states
    )
    if added <= limit:
        return Verdict.of([])

    return Verdict.of([Finding(
        rule=structure.CHANGE_TOO_LARGE,
        status=policy.structure.severity,
        file=f"{len(states)} files",
        line=0,
        detail=f"This change adds {added} lines across {len(states)} files, "
               f"over the limit of {limit}.",
        prescription=(
            "Split it into changes that can each be reviewed and reverted "
            "independently. A change this size is approved rather than read."
        ),
        confidence=Confidence.EXACT,
    )])


def _collect(changes, fetch: Reader, policy: Policy):
    """Resolve each change to (path, before, after), collecting what could not be."""
    states: list[tuple[str, str | None, str | None]] = []
    skipped: list[str] = []

    for change in changes:
        path = change.path
        if change.binary:
            skipped.append(f"{path}: binary file")
            continue
        if not change.hunks:
            skipped.append(f"{path}: no hunks in diff")
            continue

        after = "" if change.deleted else fetch(path)
        if after is None:
            skipped.append(f"{path}: cannot read the after-state to reconstruct the diff")
            continue
        try:
            before = "" if change.added else diffmod.reverse_apply(after, change.hunks)
        except diffmod.PatchError as exc:
            skipped.append(f"{path}: {exc}")
            continue

        states.append((path, before, None if change.deleted else after))

    return states, Verdict.of([], skipped=skipped)


def _pool(states, policy: Policy) -> dict[str, Relation]:
    """Strongest relation per subject across the after-state of every changed file."""
    pooled: dict[str, Relation] = {}
    for path, _before, after in states:
        if after is None or not policy.protects(path) or not path.endswith(EXACT_SUFFIXES):
            continue
        extraction = extract(after, filename=path)
        if not extraction.ok:
            continue
        for subject, relation in monotonicity.subject_map(extraction).items():
            current = pooled.get(subject)
            if current is None or relation.rank > current.rank:
                pooled[subject] = relation
    return pooled


def _pool_definitions(states) -> frozenset[str]:
    """Every module-level name defined anywhere in the change set.

    Moving a function between modules must not read as deleting it.
    """
    from .core.symbols import scan

    names: set[str] = set()
    for path, _before, after in states:
        if after is None or not path.endswith(EXACT_SUFFIXES):
            continue
        symbols = scan(after, filename=path)
        if symbols.ok:
            names.update(symbols.definitions)
    return frozenset(names)


def _read_file(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _generated(before, after, path, policy, hand_edit) -> Verdict | None:
    """Short-circuit for generated files. ``None`` means the file looks authored.

    Generated output is not analysed as authored source: nobody wrote its
    assertions, and its style is not a person's choice. Editing it by hand is
    reported, because the next build discards the edit — the fix belongs in the
    source or the template.
    """
    if not policy.generated.detect:
        return None

    origin = generatedmod.detect(
        path, after or before, extra_patterns=policy.generated.extra_patterns
    )
    if origin is None:
        return None

    status = policy.generated.on_hand_edit
    modified = before is not None and after is not None and before != after
    if hand_edit and modified and status is not None:
        return Verdict.of(
            [Finding(
                rule=GENERATED_FILE_EDITED,
                status=status,
                file=path,
                line=1,
                detail=f"{path} is generated code — {origin.reason}.",
                prescription=(
                    "Do not edit generated output by hand; the next build will discard "
                    "the change. Edit the source it is generated from, or the generator "
                    "configuration, and regenerate."
                ),
                confidence=Confidence.EXACT,
            )],
            skipped=[f"{path}: generated code, not verified as authored source"],
        )
    return Verdict.of([], skipped=[f"{path}: generated code ({origin.reason})"])
