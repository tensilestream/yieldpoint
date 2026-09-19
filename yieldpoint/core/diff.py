"""Unified diff parsing and exact before-state reconstruction.

A unified diff does not contain whole files, only changed hunks with a little
context — so it cannot be analysed directly by a checker that needs to parse
both sides. But it does contain *every removed line and its position*, which
means that given the after-state, the before-state can be rebuilt exactly.

That is what :func:`reverse_apply` does, and it is why this module needs no git:
the after-state is on disk, and the diff supplies the rest. Reconstruction is
exact, not heuristic — if the diff does not line up with the file, it says so
instead of guessing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_GIT_HEADER = re.compile(r"^diff --git (?:a/)?(.+?) (?:b/)?(.+)$")

NO_NEWLINE = "\\ No newline at end of file"


class PatchError(ValueError):
    """The diff does not apply to the content supplied."""


@dataclass(frozen=True)
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: tuple[str, ...]

    def old_side(self) -> list[str]:
        """The lines this hunk replaced, without their markers."""
        return [ln[1:] for ln in self.lines if ln[:1] in (" ", "-", "")]


@dataclass(frozen=True)
class FileChange:
    old_path: str | None
    new_path: str | None
    hunks: tuple[Hunk, ...] = ()
    binary: bool = False

    @property
    def path(self) -> str:
        return self.new_path or self.old_path or ""

    @property
    def added(self) -> bool:
        return self.old_path is None and self.new_path is not None

    @property
    def deleted(self) -> bool:
        return self.new_path is None and self.old_path is not None

    @property
    def renamed(self) -> bool:
        return bool(self.old_path and self.new_path and self.old_path != self.new_path)


def parse(diff_text: str) -> tuple[FileChange, ...]:
    """Parse a unified diff. Unrecognised lines are ignored, never guessed at."""
    changes: list[FileChange] = []
    old_path: str | None = None
    new_path: str | None = None
    header_paths: tuple[str, str] | None = None
    hunks: list[Hunk] = []
    hunk_lines: list[str] = []
    current: Hunk | None = None
    binary = False
    started = False

    def flush_hunk() -> None:
        nonlocal current, hunk_lines
        if current is not None:
            hunks.append(
                Hunk(current.old_start, current.old_count,
                     current.new_start, current.new_count, tuple(hunk_lines))
            )
        current, hunk_lines = None, []

    def flush_file() -> None:
        nonlocal old_path, new_path, hunks, binary, started, header_paths
        flush_hunk()
        if started:
            changes.append(FileChange(old_path, new_path, tuple(hunks), binary))
        old_path = new_path = None
        header_paths = None
        hunks, binary, started = [], False, False

    for raw in diff_text.splitlines():
        header = _GIT_HEADER.match(raw)
        if header:
            flush_file()
            started = True
            header_paths = (header.group(1), header.group(2))
            old_path, new_path = header_paths
            continue

        if raw.startswith("--- "):
            flush_hunk()
            if not started:
                started = True
            old_path = _path(raw[4:])
            continue

        if raw.startswith("+++ "):
            new_path = _path(raw[4:])
            continue

        if raw.startswith("Binary files") or raw.startswith("GIT binary patch"):
            binary = True
            continue

        match = _HUNK.match(raw)
        if match:
            flush_hunk()
            started = True
            current = Hunk(
                int(match.group(1)), int(match.group(2) or 1),
                int(match.group(3)), int(match.group(4) or 1), (),
            )
            continue

        if current is not None:
            if raw == NO_NEWLINE:
                continue
            if raw[:1] in (" ", "+", "-") or raw == "":
                hunk_lines.append(raw)

    flush_file()
    return tuple(changes)


def reverse_apply(after: str, hunks: tuple[Hunk, ...]) -> str:
    """Rebuild the before-state from the after-state and the diff's hunks.

    Raises :class:`PatchError` when the hunks do not line up with ``after``,
    because a silently mismatched reconstruction would produce a confident and
    completely wrong verdict.
    """
    after_lines = after.splitlines()
    result: list[str] = []
    cursor = 0

    for hunk in sorted(hunks, key=lambda h: h.new_start):
        # A hunk with no new lines sits *after* the named line, not at it.
        start = hunk.new_start - 1 if hunk.new_count else hunk.new_start
        if start < cursor or start > len(after_lines):
            raise PatchError(
                f"hunk at new line {hunk.new_start} does not fit a file of "
                f"{len(after_lines)} lines"
            )
        result.extend(after_lines[cursor:start])

        expected = [ln[1:] for ln in hunk.lines if ln[:1] in (" ", "+")]
        actual = after_lines[start:start + hunk.new_count]
        if expected != actual:
            raise PatchError(
                f"content at new line {hunk.new_start} does not match the diff"
            )

        result.extend(hunk.old_side())
        cursor = start + hunk.new_count

    result.extend(after_lines[cursor:])
    text = "\n".join(result)
    return text + "\n" if text and after.endswith("\n") else text


def _path(value: str) -> str | None:
    """Strip the a/ or b/ prefix; ``/dev/null`` means the file did not exist."""
    cleaned = value.split("\t")[0].strip()
    if cleaned == "/dev/null":
        return None
    for prefix in ("a/", "b/"):
        if cleaned.startswith(prefix):
            return cleaned[2:]
    return cleaned
