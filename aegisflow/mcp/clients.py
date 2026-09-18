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
from dataclasses import dataclass
from pathlib import Path

COMMAND = "aegisflow"
ARGS = ["mcp"]


@dataclass(frozen=True)
class Client:
    key: str
    label: str
    scope: str
    section: str = "mcpServers"
    style: str = "plain"
    note: str = ""

    def entry(self) -> dict:
        if self.style == "zed":
            return {"command": {"path": COMMAND, "args": list(ARGS)}}
        if self.style == "vscode":
            return {"type": "stdio", "command": COMMAND, "args": list(ARGS)}
        return {"command": COMMAND, "args": list(ARGS)}


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
    import sys

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
