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
from dataclasses import dataclass
from pathlib import Path

from .mcp.clients import (
    BY_KEY, CLIENTS, command_line, install as install_client, snippet,
)

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

    # Resolved rather than hard-coded: a hook registered as a bare "aegisflow"
    # that is not on the editor's PATH fails on every edit, and the failure
    # surfaces as a hook error rather than as a missing install.
    command = command_line("hook") + (" --advisory" if args.advisory else "")
    entry = {"matcher": HOOK_MATCHER, "hooks": [{"type": "command", "command": command}]}

    hooks = settings.setdefault("hooks", {})
    pre = hooks.setdefault("PreToolUse", [])
    pre[:] = [e for e in pre if not _is_aegisflow(e)] + [entry]

    path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    mode = "advisory" if args.advisory else "blocking"
    print(f"registered '{command}' on {HOOK_MATCHER} in {path} ({mode} mode)")
    print("Restart Claude Code, or start a new session, for it to take effect.")
    return EXIT_OK


STARTER_CONFIG = {
    "version": 1,
    "test_contract": {
        "_comment": "Severities: repair (send the agent back), escalate (ask a "
                    "human), block (refuse), or null to switch a rule off.",
        "assertion_monotonicity": "repair",
        "forbid_vacuous_assertions": "repair",
        "forbid_new_skip_markers": "repair",
        "forbid_swallowed_exceptions": "repair",
    },
    "structure": {
        "_comment": "Differential by default: a limit is reported only when this "
                    "change introduced or worsened the violation, so existing debt "
                    "is not blamed on the current edit.",
        "greenfield": False,
        "severity": "repair",
    },
}


def init(args) -> int:
    """Wire up everything in one command: config, MCP server, and the hook.

    Three separate commands is three chances to stop halfway, and the half that
    usually gets skipped is the hook — which is the only one that enforces
    anything. Advisory by default, because a gate that blocks on its first run
    in an unfamiliar repository gets uninstalled rather than tuned.
    """
    root = Path(args.root or ".")
    print(f"Setting up AegisFlow in {root.resolve()}\n")

    config = root / ".aegisflow.json"
    if config.is_file():
        print(f"  config   {config} already exists, left alone")
    else:
        config.write_text(json.dumps(STARTER_CONFIG, indent=2) + "\n", encoding="utf-8")
        print(f"  config   wrote {config}")

    client = BY_KEY.get(args.client or "claude-code")
    if client is None:
        print(f"aegisflow: unknown client {args.client!r}; try install-mcp --list",
              file=sys.stderr)
        return EXIT_ERROR
    try:
        path, _backup = install_client(client, root)
        print(f"  mcp      registered for {client.label} in {path}")
    except OSError as exc:
        print(f"  mcp      could not write configuration: {exc}", file=sys.stderr)

    if args.no_hook:
        print("  hook     skipped (--no-hook); nothing will enforce, only explain")
    else:
        hook_args = _HookArgs(
            settings=str(root / ".claude" / "settings.json"),
            advisory=not args.enforce,
        )
        install_hook(hook_args)

    print("\nNext:")
    print("  aegisflow review          # check what you have already changed")
    print("  restart your editor       # so it picks up the MCP server and hook")
    if not args.enforce and not args.no_hook:
        print("\nThe hook is advisory: it reports and never blocks. Re-run with")
        print("  aegisflow init --enforce   once you are happy with what it reports.")
    return EXIT_OK


@dataclass
class _HookArgs:
    """The arguments ``install_hook`` reads, so ``init`` can call it directly."""

    settings: str
    advisory: bool


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
