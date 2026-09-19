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
    """One MCP client: where its configuration lives and what shape it takes.

    ``fmt`` is what stops this table from lying. Several clients configure MCP
    in YAML or TOML, and this package has no runtime dependencies and therefore
    no parser for either. Those entries are ``--show`` only: the snippet is
    printed in the right format and the writer refuses, rather than corrupting
    a file it cannot actually read.
    """

    key: str
    label: str
    scope: str
    section: str = "mcpServers"
    style: str = "plain"
    note: str = ""
    fmt: str = "json"
    path: str = ""
    """Config location. ``~`` is the home directory; a bare relative path is
    resolved against the project root."""

    @property
    def writable(self) -> bool:
        return self.fmt == "json"

    def entry(self) -> dict:
        command, args = command_argv("mcp")
        if self.style == "zed":
            return {"command": {"path": command, "args": args}}
        if self.style == "vscode":
            return {"type": "stdio", "command": command, "args": args}
        return {"command": command, "args": args}


_VSCODE_STORAGE = {
    "darwin": "~/Library/Application Support/Code/User/globalStorage",
    "win32": "~/AppData/Roaming/Code/User/globalStorage",
    "linux": "~/.config/Code/User/globalStorage",
}

CLIENTS: tuple[Client, ...] = (
    # --- project-scoped: committed, so a team shares one configuration -------
    Client("claude-code", "Claude Code", "project", path=".mcp.json",
           note="committed to the repo, so teammates inherit it"),
    Client("vscode", "VS Code", "project", section="servers", style="vscode",
           path=".vscode/mcp.json"),
    Client("cursor-project", "Cursor (project)", "project", path=".cursor/mcp.json"),
    Client("kiro", "Kiro", "project", path=".kiro/settings/mcp.json"),
    Client("trae", "Trae", "project", path=".trae/mcp.json"),

    # --- user-scoped --------------------------------------------------------
    Client("claude-desktop", "Claude Desktop", "user"),
    Client("cursor", "Cursor", "user", path="~/.cursor/mcp.json"),
    Client("windsurf", "Windsurf", "user",
           path="~/.codeium/windsurf/mcp_config.json"),
    Client("zed", "Zed", "user", section="context_servers", style="zed",
           path="~/.config/zed/settings.json"),
    Client("cline", "Cline", "user", path="", note="VS Code extension storage"),
    Client("roo", "Roo Code", "user", path="", note="VS Code extension storage"),
    Client("gemini-cli", "Gemini CLI", "user", path="~/.gemini/settings.json"),
    Client("amazonq", "Amazon Q Developer CLI", "user",
           path="~/.aws/amazonq/mcp.json"),
    Client("opencode", "opencode", "user", path="~/.config/opencode/config.json",
           section="mcp"),
    Client("librechat", "LibreChat", "project", fmt="yaml", path="librechat.yaml",
           note="YAML — --show only"),
    Client("continue", "Continue", "user", fmt="yaml",
           path="~/.continue/config.yaml", note="YAML — --show only"),
    Client("goose", "Goose", "user", fmt="yaml", section="extensions",
           path="~/.config/goose/config.yaml", note="YAML — --show only"),
    Client("codex", "Codex CLI", "user", fmt="toml", section="mcp_servers",
           path="~/.codex/config.toml", note="TOML — --show only"),
)

BY_KEY = {client.key: client for client in CLIENTS}


def config_path(client: Client, root: Path | None = None) -> Path:
    """Where this client reads its MCP configuration.

    Driven by the table, so adding a client stays a data change. Two entries
    need code because their location is computed rather than fixed: Claude
    Desktop differs per operating system, and the VS Code extensions live under
    a per-platform extension storage directory.
    """
    base = root or Path.cwd()
    home = Path.home()
    if client.path:
        if client.path.startswith("~"):
            return home / client.path[2:]
        return base / client.path
    if client.key in _EXTENSION_STORAGE:
        return _extension_config(home, client.key)
    return _claude_desktop(home)


#: VS Code extensions that keep MCP settings in their own storage directory.
_EXTENSION_STORAGE = {
    "cline": ("saoudrizwan.claude-dev", "cline_mcp_settings.json"),
    "roo": ("rooveterinaryinc.roo-cline", "mcp_settings.json"),
}


def _extension_config(home: Path, key: str) -> Path:
    publisher, filename = _EXTENSION_STORAGE[key]
    root = _VSCODE_STORAGE.get(sys.platform, _VSCODE_STORAGE["linux"])
    return home / root[2:] / publisher / "settings" / filename


def _claude_desktop(home: Path) -> Path:
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", home)) / "Claude" / "claude_desktop_config.json"
    if _is_macos():
        return home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    return home / ".config" / "Claude" / "claude_desktop_config.json"


def _is_macos() -> bool:
    return sys.platform == "darwin"


class UnwritableFormat(Exception):
    """This client's configuration is not JSON, so it can only be shown."""


def install(client: Client, root: Path | None = None,
            path: Path | None = None) -> tuple[Path, Path | None]:
    """Register AegisFlow with ``client``. Returns (config path, backup path).

    ``path`` overrides the table, which is how a client this module has never
    heard of still gets configured.
    """
    if not client.writable:
        raise UnwritableFormat(
            f"{client.label} is configured in {client.fmt.upper()}, which this "
            "package cannot parse without a dependency. Use --show and paste it."
        )
    path = path or config_path(client, root)
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
    """The configuration to paste, in the format that client actually reads."""
    command, args = command_argv("mcp")
    if client.fmt == "toml":
        rendered = ", ".join(f'"{a}"' for a in args)
        return (f"[{client.section}.aegisflow]\n"
                f'command = "{command}"\n'
                f"args = [{rendered}]")
    if client.fmt == "yaml":
        lines = [f"{client.section}:", "  aegisflow:", f"    command: {command}"]
        lines.append("    args:")
        lines.extend(f"      - {a}" for a in args)
        return "\n".join(lines)
    return json.dumps({client.section: {"aegisflow": client.entry()}}, indent=2)


def command_line(*subcommand: str) -> str:
    """``command_argv`` as a shell string, for configurations that take one."""
    command, args = command_argv(*subcommand)
    return " ".join(shlex.quote(part) for part in (command, *args))
