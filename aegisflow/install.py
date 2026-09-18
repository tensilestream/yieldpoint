"""Wiring AegisFlow into the tools that will call it.

Two doors, and they do different jobs. The hook **enforces**: a PreToolUse gate
can deny an edit, so an agent cannot route around it. MCP **explains**: it is a
tool the agent chooses to call, which is excellent for answering "why was that
rejected, and what should I do" and useless as a gate, because an agent intent on
weakening a test simply will not ask.

Both back up whatever they find before writing to it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .mcp.clients import BY_KEY, CLIENTS, install as install_client, snippet

EXIT_OK, EXIT_ERROR = 0, 2

HOOK_MATCHER = "Edit|MultiEdit|Write"


def mcp_command(args) -> int:
    """Run the MCP server on stdio. Nothing may be printed to stdout but protocol."""
    from .mcp.server import serve

    return serve(policy=getattr(args, "policy", None))


def install_mcp(args) -> int:
    """Register the server with an editor, or show the snippet to paste."""
    if getattr(args, "list", False) or not getattr(args, "client", None):
        print("Clients AegisFlow can configure:\n")
        for client in CLIENTS:
            note = f"  ({client.note})" if client.note else ""
            print(f"  {client.key:16} {client.label:16} {client.scope}-level{note}")
        print("\n  aegisflow install-mcp --client claude-code")
        print("  aegisflow install-mcp --client cursor --show   # print, do not write")
        print("\nPaths and formats are set by each vendor and do change; --show prints")
        print("the snippet if you would rather wire it up yourself.")
        return EXIT_OK

    client = BY_KEY.get(args.client)
    if client is None:
        print(f"aegisflow: unknown client {args.client!r}; try --list", file=sys.stderr)
        return EXIT_ERROR

    if getattr(args, "show", False):
        from .mcp.clients import config_path

        print(f"# {client.label}  ->  {config_path(client)}")
        print(snippet(client))
        return EXIT_OK

    try:
        path, backup = install_client(client)
    except OSError as exc:
        print(f"aegisflow: could not write configuration: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if backup:
        print(f"backed up existing configuration to {backup}")
    print(f"registered the AegisFlow MCP server for {client.label} in {path}")
    print("Restart the editor for it to connect.")
    return EXIT_OK


def install_hook(args) -> int:
    path = Path(args.settings) if args.settings else Path(".claude/settings.json")
    path.parent.mkdir(parents=True, exist_ok=True)

    settings: dict = {}
    if path.is_file():
        try:
            settings = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"aegisflow: cannot read {path}: {exc}", file=sys.stderr)
            return EXIT_ERROR
        backup = path.with_suffix(path.suffix + ".aegisflow-backup")
        backup.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        print(f"backed up existing settings to {backup}")

    command = "aegisflow hook" + (" --advisory" if args.advisory else "")
    entry = {"matcher": HOOK_MATCHER, "hooks": [{"type": "command", "command": command}]}

    hooks = settings.setdefault("hooks", {})
    pre = hooks.setdefault("PreToolUse", [])
    pre[:] = [e for e in pre if not _is_aegisflow(e)] + [entry]

    path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    mode = "advisory" if args.advisory else "blocking"
    print(f"registered '{command}' on {HOOK_MATCHER} in {path} ({mode} mode)")
    print("Restart Claude Code, or start a new session, for it to take effect.")
    return EXIT_OK


# ------------------------------------------------------------------- helpers


def _is_aegisflow(entry: object) -> bool:
    if not isinstance(entry, dict):
        return False
    return any(
        isinstance(h, dict) and "aegisflow" in str(h.get("command", ""))
        for h in entry.get("hooks", [])
    )


def _is_aegisflow(entry: object) -> bool:
    if not isinstance(entry, dict):
        return False
    return any(
        isinstance(h, dict) and "aegisflow" in str(h.get("command", ""))
        for h in entry.get("hooks", [])
    )
