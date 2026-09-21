"""Where a new file was put, given what is already there.

One of the failure modes a field review named as characteristic of
agent-written code: a new ``foo_bar.py`` dropped beside an existing ``foo/``
package. The code belongs in ``foo/bar.py``. Nothing is broken, the tests pass,
and the package quietly acquires a second place to look for the same concern —
which is how a tree stops being navigable.

An agent does this because it can see the file it is writing and not the
directory it is writing into. The directory is the cheapest fact there is.

Only new files are examined. A repository that already has such a pair made
that decision at some point, possibly on purpose, and re-litigating it on every
run is how a rule gets switched off.
"""

from __future__ import annotations

from pathlib import Path

from .verdict import Confidence, Finding, Status

SIBLING_MODULE = "sibling_module_shadows_package"

#: Marks a directory as a package rather than a folder that happens to sit
#: there. Without this, any directory sharing a prefix would match.
_PACKAGE = "__init__.py"


def _package_for(stem: str, parent: Path) -> tuple[str, str] | None:
    """The existing package this module's name reaches into, if any.

    Longest prefix first: with both ``foo/`` and ``foo_bar/`` present,
    ``foo_bar_baz.py`` belongs to the more specific one.
    """
    parts = stem.split("_")
    for cut in range(len(parts) - 1, 0, -1):
        name, rest = "_".join(parts[:cut]), "_".join(parts[cut:])
        # An empty prefix would resolve to the parent's own ``__init__.py`` and
        # report every privately-named module in a package: `_private.py`
        # "belongs in" `private.py`. A leading underscore is a visibility
        # convention, not a package name. An empty remainder is no name at all.
        if name and rest and (parent / name / _PACKAGE).is_file():
            return name, rest
    return None


def check(new_files, root: Path, severity: Status | None) -> list[Finding]:
    """Report new modules whose name reaches into a package beside them."""
    if severity is None:
        return []
    findings = []
    for path in new_files:
        target = Path(path)
        if target.suffix != ".py" or "_" not in target.stem.strip("_"):
            continue
        match = _package_for(target.stem, root / target.parent)
        if match is None:
            continue
        package, rest = match
        belongs = target.parent / package / f"{rest}.py"
        findings.append(Finding(
            rule=SIBLING_MODULE, status=severity, file=str(path), line=1,
            detail=f"`{target.name}` is new, and `{package}/` already exists "
                   f"beside it. The name says it belongs to that package.",
            prescription=f"Move it to `{belongs.as_posix()}`. A prefix is a "
                         "package spelled in a way imports cannot use.",
            confidence=Confidence.EXACT,
        ))
    return findings


__all__ = ["SIBLING_MODULE", "check"]
