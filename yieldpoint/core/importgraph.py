"""Which modules depend on which, and therefore what is load-bearing.

Asking an engineer to list the important paths does not work for long. Somebody
writes it once, a directory is renamed, and the list silently stops matching —
the worst failure a safety control can have, because it goes on reporting
success. And the list encodes one person's belief about a codebase on one day.

Most of what that list is trying to say is already in the code: **a module that
forty others import is load-bearing, and one nothing imports is not.** That is
computable, it updates itself, and it does not depend on anyone remembering.

Two grades of answer, and they are not interchangeable:

*Exact* — Python, parsed. Every import is found, including aliased and
conditional ones.

*Lexical* — everything else, matched. It reads ``import``/``require``/``use``
lines with a regular expression, which finds most real imports and will miss
one built at runtime. Findings derived this way carry ``Confidence.LEXICAL``
and are therefore never permitted to block (verdict.py).

**What this does not know.** Fan-in measures blast radius, not importance. A
payments calculation imported by one caller is still the most dangerous file in
the repository. This narrows what a human has to declare; it does not remove it.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

#: Import forms across the ecosystems this is likely to meet. Deliberately
#: loose: a false import edge slightly over-states one module's importance,
#: while a missed one under-states it, and over-stating is the safer error.
_LEXICAL_IMPORT = re.compile(
    r"""(?:^|\n)\s*(?:
        import\s+(?:[\w*\s{},]+\s+from\s+)?["'](?P<from>[^"']+)["']   # JS/TS
      | (?:const|let|var)\s+.*?require\(\s*["'](?P<req>[^"']+)["']    # CommonJS
      | import\s+(?:static\s+)?(?P<java>[\w.]+)\s*;                   # Java/Kotlin
      | use\s+(?P<rust>[\w:]+)\s*;                                    # Rust
      | (?:^|\n)\s*import\s+(?P<go>"[^"]+")                           # Go
      | using\s+(?P<cs>[\w.]+)\s*;                                    # C#
    )""",
    re.VERBOSE | re.MULTILINE,
)

EXACT_SUFFIXES = (".py",)
LEXICAL_SUFFIXES = (
    ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".java", ".kt", ".go", ".rs", ".cs",
)


@dataclass(frozen=True)
class Graph:
    """Who imports whom, across one repository."""

    fan_in: dict[str, int] = field(default_factory=dict)
    fan_out: dict[str, int] = field(default_factory=dict)
    modules: tuple[str, ...] = ()
    exact: bool = True
    """False when any file was read lexically, which caps what may be concluded."""

    def importance(self, path: str) -> float:
        """Where this module sits in *this* repository's distribution, 0..1.

        A percentile rather than a count, because a fan-in of ten means
        something different in a fifty-file service and a five-thousand-file
        monolith. This is the part that makes a single default work across
        codebases of different sizes without anyone tuning it.
        """
        if not self.fan_in:
            return 0.0
        mine = self.fan_in.get(_key(path))
        if mine is None:
            return 0.0
        counts = sorted(self.fan_in.values())
        below = sum(1 for value in counts if value < mine)
        return below / len(counts)

    def depends_on_me(self, path: str) -> int:
        return self.fan_in.get(_key(path), 0)


def build(root: str | Path, paths=None) -> Graph:
    """Read the repository once and record its import edges."""
    base = Path(root)
    files = list(paths) if paths is not None else _walk(base)

    keyed = [
        (_key(str(p.relative_to(base)) if p.is_relative_to(base) else str(p)), p)
        for p in files
    ]
    # Only edges *into this repository* count. Without this the ranking is led
    # by `typing` and `dataclasses`, which says nothing about anyone's code.
    own = {key for key, _ in keyed}

    fan_in: dict[str, int] = {key: 0 for key in own}
    fan_out: dict[str, int] = {}
    exact = True

    for key, path in keyed:
        internal, precise = _edges(path, key, own)
        exact = exact and precise
        fan_out[key] = len(internal)
        for resolved in internal:
            fan_in[resolved] += 1

    return Graph(
        fan_in=fan_in, fan_out=fan_out,
        modules=tuple(sorted(own)), exact=exact,
    )


def _edges(path: Path, key: str, own: set[str]) -> tuple[set[str], bool]:
    """Imports from one file that land inside this repository.

    Returns the targets and whether they were found exactly. A file that cannot
    be read contributes no edges rather than failing the build — one unreadable
    file should not cost the ranking of every other.
    """
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return set(), True

    if path.name.endswith(EXACT_SUFFIXES):
        targets, precise = _python_imports(source), True
    else:
        targets, precise = _lexical_imports(source), False

    internal = {
        resolved for target in targets
        if (resolved := _resolve(target, key)) in own and resolved != key
    }
    return internal, precise


def _walk(base: Path):
    suffixes = EXACT_SUFFIXES + LEXICAL_SUFFIXES
    for path in sorted(base.rglob("*")):
        if path.is_file() and path.name.endswith(suffixes):
            yield path


def _python_imports(source: str) -> list[str]:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return []
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append(node.module)
    return found


def _lexical_imports(source: str) -> list[str]:
    found = []
    for match in _LEXICAL_IMPORT.finditer(source):
        target = next((v for v in match.groupdict().values() if v), None)
        if target:
            found.append(target.strip('"').strip("'"))
    return found


def _resolve(target: str, importer: str) -> str | None:
    """Map an import target onto a module key in this repository.

    Relative and dotted forms both reduce to the last meaningful segment. This
    is approximate on purpose: an exact resolver needs each language's module
    system, and the ranking only needs to be right about which modules are
    heavily depended upon, not about every edge.
    """
    cleaned = target.replace("\\", "/").strip("./")
    if not cleaned:
        return None
    tail = cleaned.split("/")[-1].split(".")[-1] if "/" in cleaned else cleaned.split(".")[-1]
    return tail or None


def _key(path: str) -> str:
    """A module's identity: its file stem, which is what an import names."""
    name = path.replace("\\", "/").split("/")[-1]
    for suffix in EXACT_SUFFIXES + LEXICAL_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


__all__ = ["Graph", "build", "EXACT_SUFFIXES", "LEXICAL_SUFFIXES"]
