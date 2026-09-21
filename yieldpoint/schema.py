"""Every setting this build accepts, derived from the code that reads them.

A field review asked for the config to say not just what a threshold *is* but
what may be put there: which keys exist, what type each takes, what the legal
values are, and what switching one off looks like. Without that an agent told
to tune a limit invents a key name, and an invented key is silently ignored.

The obvious home for that is a comment block written into the config at
install time. It is the wrong one: it describes the version that wrote it, and
goes stale the first time Yieldpoint is upgraded. So this is a command instead,
and everything in it is read from the policy dataclasses and their own source.
A field that exists is listed; a field that does not, is not. A new setting
cannot ship undocumented because nothing here was written by hand.

Provenance matters as much as the value. ``limit 50 (default)`` and
``limit 50 (.yieldpoint.json)`` call for different edits, and a reader cannot
tell them apart from the number.
"""

from __future__ import annotations

import ast
import dataclasses
import json
from pathlib import Path
from typing import Any

from .core.policy import Policy
from .core.verdict import Status

#: Sections that describe a run rather than configure one.
_INTERNAL = frozenset({"source", "warnings"})

_STATUSES = [s.value for s in Status if s not in (Status.PASS, Status.UNVERIFIED)]


@dataclasses.dataclass(frozen=True)
class Setting:
    """One configurable value, and everything needed to change it."""

    section: str
    name: str
    type: str
    legal: str
    default: Any
    value: Any
    source: str
    note: str = ""

    @property
    def key(self) -> str:
        return f"{self.section}.{self.name}" if self.section else self.name

    @property
    def changed(self) -> bool:
        return self.source != "default"


def _field_notes(source: Path) -> dict[tuple[str, str], str]:
    """Field docstrings, read from the module that declares the fields.

    Parsed rather than imported because Python discards a docstring written
    under a dataclass field. Reading the source keeps the explanation and the
    field in one place, which is the only arrangement that cannot drift.
    """
    try:
        tree = ast.parse(source.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError):
        return {}
    return {(node.name, field): note
            for node in tree.body if isinstance(node, ast.ClassDef)
            for field, note in _class_notes(node).items()}


def _is_text(statement) -> bool:
    return (isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str))


def _class_notes(node: ast.ClassDef) -> dict[str, str]:
    """Docstrings written directly beneath an annotated field, by field name."""
    notes: dict[str, str] = {}
    pending = ""
    for statement in node.body:
        if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            pending = statement.target.id
        elif pending and _is_text(statement):
            notes[pending] = " ".join(statement.value.value.split())
            pending = ""
        else:
            pending = ""
    return notes


def _legal(annotation: str, default: Any) -> str:
    """What may be written here, phrased for whoever has to write it."""
    if isinstance(default, Status) or "Status" in annotation:
        return f"{', '.join(_STATUSES)}, or null to switch the rule off"
    if annotation.startswith("bool") or isinstance(default, bool):
        return "true or false"
    if "int" in annotation:
        off = ", or null for no limit" if "None" in annotation else ""
        return f"a whole number{off}"
    if "float" in annotation:
        return "a number"
    if "tuple" in annotation or isinstance(default, tuple):
        return _legal_sequence(annotation)
    return "text"


def _legal_sequence(annotation: str) -> str:
    """Read off the element type rather than assumed: a list of zone objects
    and a list of glob strings are edited very differently."""
    if "tuple[str" in annotation:
        return "a list of strings"
    return "a list of objects — see the rules reference for its shape"


def _render(value: Any) -> Any:
    """A value in a form JSON can carry, without pretending to carry a structure.

    Lists of configured objects — zones, custom rules — are reported as a count
    rather than expanded. Their shape is the one thing this module cannot
    derive, and inventing a rendering for it would be the stale comment block
    all over again.
    """
    if isinstance(value, Status):
        return value.value
    if isinstance(value, tuple):
        if any(dataclasses.is_dataclass(item) for item in value):
            return f"({len(value)} configured)"
        return list(value)
    if dataclasses.is_dataclass(value):
        return "(object)"
    return value


def _present(raw: dict, section: str, name: str) -> bool:
    if section:
        block = raw.get(section)
        return isinstance(block, dict) and name in block
    return name in raw


def _raw(path: str | None) -> dict:
    if not path:
        return {}
    try:
        loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _settings_of(block, section: str, raw: dict, notes: dict) -> list[Setting]:
    defaults = type(block)()
    out = []
    for field in dataclasses.fields(block):
        if field.name in _INTERNAL:
            continue
        default = getattr(defaults, field.name)
        origin = ".yieldpoint.json" if _present(raw, section, field.name) else "default"
        out.append(Setting(
            section=section, name=field.name, type=str(field.type),
            legal=_legal(str(field.type), default),
            default=_render(default), value=_render(getattr(block, field.name)),
            source=origin, note=notes.get((type(block).__name__, field.name), ""),
        ))
    return out


def settings(policy: Policy, path: str | None = None) -> list[Setting]:
    """Every setting this build accepts, with the value in force and its source."""
    raw = _raw(path)
    notes = _field_notes(Path(__file__).parent / "core" / "policysections.py")
    found = _settings_of(policy, "", raw, notes)
    for field in dataclasses.fields(policy):
        block = getattr(policy, field.name)
        if dataclasses.is_dataclass(block) and not isinstance(block, type):
            found.extend(_settings_of(block, field.name, raw, notes))
    return [s for s in found if s.value != "(object)"]


def to_dict(found: list[Setting]) -> dict:
    """The machine-readable form, because the reader is often not a person."""
    return {"settings": [{
        "key": s.key, "type": s.type, "legal": s.legal,
        "default": s.default, "value": s.value, "source": s.source,
        "note": s.note,
    } for s in found]}


def render(found: list[Setting], path: str | None) -> str:
    where = path or "no .yieldpoint.json found — every value below is a built-in default"
    lines = [f"POLICY IN FORCE — {where}", ""]
    for setting in found:
        mark = "*" if setting.changed else " "
        lines.append(f" {mark} {setting.key:44} {str(setting.value):<22} ({setting.source})")
        lines.append(f"     {setting.legal}")
        if setting.note:
            lines.append(f"     {setting.note[:150]}")
    lines.append("")
    lines.append("  * set in this repository; everything else is a built-in default.")
    lines.append("  Changing a limit is itself reported, as `policy_weakened`.")
    return "\n".join(lines)


def drifted(found: list[Setting]) -> list[Setting]:
    """Settings this repository states that differ from this build's default."""
    return [s for s in found if s.changed and s.value != s.default]


def render_drift(found: list[Setting], stamp: str, running: str) -> str:
    """What is frozen, and from when.

    A value chosen on purpose and a default frozen at install look identical in
    the file. Both are listed, because the tool cannot tell them apart and
    should not pretend to — the stamp says which build wrote the file, which is
    the most this can honestly offer.
    """
    apart = drifted(found)
    origin = (f"written by {stamp}; running {running}" if stamp
              else f"this policy does not record which build wrote it; "
                   f"running {running}")
    if not apart:
        return f"POLICY DRIFT — nothing differs from this build's defaults\n  {origin}"
    lines = [f"POLICY DRIFT — {len(apart)} setting(s) differ from this build's "
             f"defaults", f"  {origin}", ""]
    for setting in apart:
        lines.append(f"  {setting.key:44} {str(setting.value):<20} "
                     f"(this build defaults to {setting.default})")
    lines.append("")
    lines.append("  A value chosen on purpose and a default frozen at install "
                 "look the same here.")
    lines.append("  Nothing is changed by this command. Deciding which is which "
                 "is yours.")
    return "\n".join(lines)


def policy_command(args) -> int:
    from .policyfile import locate

    root = getattr(args, "root", ".") or "."
    found_at = args.policy or (str(locate(root)) if locate(root) else None)
    try:
        policy = Policy.load(args.policy, root=root)
    except (OSError, ValueError) as exc:
        print(f"yieldpoint: {exc}")
        return 2
    found = settings(policy, found_at)
    if getattr(args, "drift", False):
        from . import __version__
        from .policyfile import written_by

        print(render_drift(found, written_by(root), __version__))
        return 0
    print(json.dumps(to_dict(found), indent=2) if args.json else render(found, found_at))
    return 0


def add_command(sub) -> None:
    command = sub.add_parser(
        "policy", help="every setting this build accepts, and the value in force")
    command.add_argument("--root", default=".")
    command.add_argument("--policy", default=None)
    command.add_argument("--json", action="store_true",
                         help="machine-readable, for an agent tuning the config")
    command.add_argument("--drift", action="store_true",
                         help="what this repository states that this build no "
                              "longer defaults to")
    command.set_defaults(handler=policy_command)


__all__ = ["Setting", "settings", "render", "render_drift", "drifted",
           "to_dict", "policy_command", "add_command"]
