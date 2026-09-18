"""Architectural boundary enforcement.

A zone is a set of files that may not import certain things: the presentation
layer may not reach the database, the verification core may not reach an adapter
or the network.

This ground is well served by `import-linter`, `dependency-cruiser` and ArchUnit,
and AegisFlow does not claim to better them. It is here because the policy file
already declares zones and because a rule an agent can be *told about in the same
verdict* is worth more than one it discovers by a separate tool failing later.

Relative imports are resolved against the file's own package, so `from ..core
import x` is compared as `aegisflow.core.x` rather than as an unresolvable dot.
Without that, a zone rule silently matches nothing — which is worse than having
no rule, because the policy file claims a protection that is not there.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

from . import glob
from .verdict import Confidence, Finding

BOUNDARY_VIOLATION = "boundary_violation"


@dataclass(frozen=True)
class Import:
    """One import, as written and as resolved."""

    module: str
    line: int
    raw: str


def imports_of(source: str, path: str) -> tuple[Import, ...]:
    """Every module imported by ``source``, with relative imports resolved."""
    try:
        tree = ast.parse(source, filename=path)
    except (SyntaxError, ValueError, RecursionError):
        return ()

    package = _package(path)
    found: list[Import] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(
                Import(alias.name, node.lineno, f"import {alias.name}")
                for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom):
            module = _resolve(node, package)
            if module:
                found.append(Import(module, node.lineno, f"from {module} import ..."))
    return tuple(found)


def check(
    before: str | None, after: str | None, path: str, config
) -> tuple[list[Finding], list[str]]:
    """Report imports this change introduced that its zone forbids."""
    if after is None or config.on_violation is None or not config.zones:
        return [], []

    zones = [zone for zone in config.zones if glob.matches(zone.path, path)]
    if not zones:
        return [], []

    existing = {
        (imported.module, pattern)
        for imported in imports_of(before or "", path)
        for pattern in _violations(imported, zones)
    }

    findings: list[Finding] = []
    for imported in imports_of(after, path):
        for zone, pattern in _matches(imported, zones):
            if (imported.module, pattern) in existing:
                continue  # already there; not introduced by this change
            findings.append(Finding(
                rule=BOUNDARY_VIOLATION,
                status=config.on_violation,
                file=path,
                line=imported.line,
                detail=(
                    f"`{path}` is in zone `{zone.name}`, which may not import "
                    f"`{imported.module}` (matches `{pattern}`)."
                ),
                prescription=(
                    zone.reason or
                    f"Remove the dependency on `{imported.module}`, or move this code "
                    f"out of `{zone.path}`. Depend on an abstraction the zone is "
                    f"allowed to see instead."
                ),
                before=imported.raw,
                confidence=Confidence.EXACT,
            ))
    return findings, []


def _matches(imported: Import, zones) -> list[tuple[object, str]]:
    hits = []
    for zone in zones:
        for pattern in zone.forbidden_imports:
            if _forbids(pattern, imported.module):
                hits.append((zone, pattern))
                break  # one finding per zone per import
    return hits


def _violations(imported: Import, zones) -> list[str]:
    return [pattern for _zone, pattern in _matches(imported, zones)]


def _forbids(pattern: str, module: str) -> bool:
    """Match a forbidden-import pattern against a dotted module name.

    Patterns are written either as module paths (`aegisflow.langgraph.*`, `requests`)
    or as file globs (`src/db/**`), because both spellings appear in the wild. The
    module is compared in both forms so either works.
    """
    if module == pattern:
        return True
    if module.startswith(f"{pattern}."):
        return True  # a bare package name forbids everything beneath it
    for suffix in (".*", ".**", "/*", "/**"):
        if pattern.endswith(suffix):
            # `a.b.*` means "anything in a.b", and importing `a.b` itself is
            # importing from it. Matching only submodules would leave the
            # package import as a hole in a rule that looks closed.
            base = pattern[: -len(suffix)]
            if module == base or module.startswith(f"{base}."):
                return True
    if glob.matches(pattern, module):
        return True
    return glob.matches(pattern, module.replace(".", "/"))


def _package(path: str) -> str:
    """The dotted package a file lives in, used to resolve relative imports."""
    # A module's package is its directory — including for `__init__.py`, where
    # `.` refers to the package the file defines rather than its parent.
    parts = glob.normalize(path).split("/")
    if parts and parts[-1].endswith(".py"):
        parts = parts[:-1]
    return ".".join(part for part in parts if part)


def _resolve(node: ast.ImportFrom, package: str) -> str:
    if not node.level:
        return node.module or ""
    parts = package.split(".") if package else []
    climbed = parts[: len(parts) - (node.level - 1)] if node.level > 1 else parts
    base = ".".join(climbed)
    if node.module:
        return f"{base}.{node.module}" if base else node.module
    return base
