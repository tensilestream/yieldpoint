"""Where each MCP client keeps its configuration, and in what shape.

Clients agree on stdio JSON-RPC and disagree on everything else: the file, the
top-level key, and whether the command is a string or an object. This module is
the whole of that knowledge, so adding a client is a data change.

**These paths and shapes change.** Vendors move them between releases, and this
table is a convenience rather than an authority — `aegisflow mcp` is the part
that matters, and it can always be wired up by hand. Existing configuration is
backed up before it is touched.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

def command_argv(*subcommand: str) -> tuple[str, list[str]]:
    """The command to register for ``subcommand``, chosen so that it actually runs.

    Returns the bare ``aegisflow`` name when the console script is on PATH.
    Bare rather than absolute on purpose: ``.mcp.json`` is committed to the
    repository, and an absolute interpreter path baked into it works on exactly
    one machine.

    Falls back to ``<interpreter> -m aegisflow``, which cannot fail to resolve —
    it names the interpreter this process is running under, in which the package
    is importable by definition. That fallback *is* machine-specific, which is
    the right trade when the alternative is a command that does not run at all.

    This matters more than it looks. An MCP client that cannot find the command
    reports a server that failed to start, not a missing PATH entry, and the
    person spends an hour on the wrong problem.
    """
    if shutil.which("aegisflow"):
        return "aegisflow", list(subcommand)
    return sys.executable, ["-m", "aegisflow", *subcommand]


@dataclass(frozen=True)
class Client:
    key: str
    label: str
    scope: str
    section: str = "mcpServers"
    style: str = "plain"
    note: str = ""

    def entry(self) -> dict:
        command, args = command_argv("mcp")
        if self.style == "zed":
            return {"command": {"path": command, "args": args}}
        if self.style == "vscode":
            return {"type": "stdio", "command": command, "args": args}
        return {"command": command, "args": args}


CLIENTS: tuple[Client, ...] = (
    Client("claude-code", "Claude Code", "project",
           note="committed to the repo, so teammates inherit it"),
    Client("claude-desktop", "Claude Desktop", "user"),
    Client("cursor", "Cursor", "user"),
    Client("windsurf", "Windsurf", "user"),
    Client("vscode", "VS Code", "project", section="servers", style="vscode"),
    Client("zed", "Zed", "user", section="context_servers", style="zed"),
)

BY_KEY = {client.key: client for client in CLIENTS}


def config_path(client: Client, root: Path | None = None) -> Path:
    """Where this client reads its MCP configuration."""
    base = root or Path.cwd()
    home = Path.home()
    if client.key == "claude-code":
        return base / ".mcp.json"
    if client.key == "vscode":
        return base / ".vscode" / "mcp.json"
    if client.key == "cursor":
        return home / ".cursor" / "mcp.json"
    if client.key == "windsurf":
        return home / ".codeium" / "windsurf" / "mcp_config.json"
    if client.key == "zed":
        return home / ".config" / "zed" / "settings.json"
    return _claude_desktop(home)


def _claude_desktop(home: Path) -> Path:
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", home)) / "Claude" / "claude_desktop_config.json"
    if _is_macos():
        return home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    return home / ".config" / "Claude" / "claude_desktop_config.json"


def _is_macos() -> bool:
    return sys.platform == "darwin"


def install(client: Client, root: Path | None = None) -> tuple[Path, Path | None]:
    """Register AegisFlow with ``client``. Returns (config path, backup path)."""
    path = config_path(client, root)
    path.parent.mkdir(parents=True, exist_ok=True)

    existing: dict = {}
    backup: Path | None = None
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        try:
            loaded = json.loads(text)
            existing = loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError:
            existing = {}
        backup = path.with_suffix(path.suffix + ".aegisflow-backup")
        backup.write_text(text, encoding="utf-8")

    section = existing.setdefault(client.section, {})
    if not isinstance(section, dict):
        section = {}
        existing[client.section] = section
    section["aegisflow"] = client.entry()

    path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    return path, backup


def snippet(client: Client) -> str:
    """The configuration to paste, for anyone who would rather do it by hand."""
    return json.dumps({client.section: {"aegisflow": client.entry()}}, indent=2)


def command_line(*subcommand: str) -> str:
    """``command_argv`` as a shell string, for configurations that take one."""
    command, args = command_argv(*subcommand)
    return " ".join(shlex.quote(part) for part in (command, *args))
