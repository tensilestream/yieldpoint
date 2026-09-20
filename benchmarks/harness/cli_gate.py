"""The fail-closed Yieldpoint CLI bridge for non-Python agent harnesses."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def _file(text: str | None) -> str | None:
    if text is None:
        return None
    handle = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False)
    with handle:
        handle.write(text)
    return handle.name


def check_change(path: str, before: str | None, after: str | None,
                 root: str = ".") -> tuple[bool, str]:
    """Return whether a change must stop, with the CLI prescription verbatim."""
    old, new = _file(before), _file(after)
    command = [sys.executable, "-m", "yieldpoint", "check", "--path", path, "--json"]
    if old:
        command.extend(("--before", old))
    if new:
        command.extend(("--after", new))
    try:
        result = subprocess.run(command, cwd=root, text=True, capture_output=True, check=False)
        payload = json.loads(result.stdout) if result.stdout else {}
    finally:
        for name in (old, new):
            if name:
                Path(name).unlink(missing_ok=True)
    return _outcome(result.returncode, payload, result.stderr)


def _outcome(code: int, payload: dict, stderr: str) -> tuple[bool, str]:
    outcomes = {
        0: (False, ""),
        3: (True, "Unknown: Yieldpoint could not analyse this change."),
        1: (True, _prescription(payload)),
    }
    if code in outcomes:
        return outcomes[code]
    detail = stderr.strip() or _prescription(payload, "Yieldpoint failed.")
    return True, detail


def _prescription(payload: dict, fallback: str = "Blocked by Yieldpoint findings.") -> str:
    direct = payload.get("prescription")
    if direct:
        return str(direct)
    items = [str(item.get("prescription", "")) for item in payload.get("findings", [])]
    return "\n".join(item for item in items if item) or fallback
