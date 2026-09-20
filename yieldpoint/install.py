"""Wiring Yieldpoint into the tools that will call it.

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

from .starter import STARTER_CONFIG
from .mcp.clients import (
    BY_KEY, CLIENTS, UnwritableFormat, command_line, config_path,
    install as install_client, snippet,
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
        return _list_clients()

    client = BY_KEY.get(args.client)
    if client is None:
        print(f"yieldpoint: unknown client {args.client!r}; try --list", file=sys.stderr)
        return EXIT_ERROR

    override = Path(args.path) if getattr(args, "path", None) else None
    if getattr(args, "show", False):
        print(f"# {client.label}  ->  {override or config_path(client)}")
        print(snippet(client))
        return EXIT_OK          # nothing installed, so nothing to gate

    try:
        path, backup = install_client(client, path=override)
    except UnwritableFormat as exc:
        print(f"yieldpoint: {exc}\n", file=sys.stderr)
        print(f"# {client.label}  ->  {config_path(client)}")
        print(snippet(client))
        return EXIT_ERROR
    except OSError as exc:
        print(f"yieldpoint: could not write configuration: {exc}", file=sys.stderr)
        return EXIT_ERROR

    _report_registration(client, path, backup)
    _gate_alongside(Path(getattr(args, "root", None) or "."),
                    bool(getattr(args, "no_git", False)))
    print("Restart the editor for it to connect.")
    return EXIT_OK


def _report_registration(client, path, backup) -> None:
    if backup:
        print(f"backed up existing configuration to {backup}")
    print(f"registered the Yieldpoint MCP server for {client.label} in {path}")


def _verify_each_turn(hooks: dict, *, advisory: bool, report: bool = True) -> None:
    """The turn-level gate, and the report, both on ``Stop``.

    Two hooks, one event, in this order for a reason.

    The ``PreToolUse`` gate above sees a tool call. It therefore sees only edits
    made with tools whose payload can be replayed — ``Write`` carries the new
    content, ``Edit`` carries the replacement. An agent that edits through the
    shell (``sed -i``, a heredoc, ``patch``) produces a payload with no
    after-state in it, so that gate is silent. It is not a matcher that can be
    widened; there is nothing in a ``Bash`` payload to verify.

    ``yieldpoint hook --stop`` asks git instead of the tool call, so it sees
    every edit regardless of which tool made it. Registering only the per-edit
    gate is what makes an install look complete and enforce nothing.

    The report is one file refreshed in place, so a page left open shows the
    current state after every turn without accumulating anything.
    """
    gate = command_line("hook", "--stop") + (" --advisory" if advisory else "")
    commands = [gate] + ([command_line("report")] if report else [])
    entry = {
        "matcher": "",
        "hooks": [{"type": "command", "command": c} for c in commands],
    }
    _register(hooks, "Stop", entry)


def _register(hooks: dict, event: str, entry: dict) -> None:
    """Put one Yieldpoint entry on an event, replacing any earlier one."""
    current = hooks.setdefault(event, [])
    current[:] = [e for e in current if not _is_yieldpoint(e)] + [entry]


def _compact_tool_output(hooks: dict) -> None:
    """Shrink JSON tool results before the model reads them.

    ``PostToolUse`` is the only place this saves anything: the tool has
    returned but the result has not entered the prompt yet. Opt-in, because
    rewriting every tool result is a bigger thing to switch on by default than
    a gate that only ever reads.
    """
    _register(hooks, "PostToolUse", {"matcher": "", "hooks": [
        {"type": "command", "command": command_line("hook", "--post")}]})


def _list_clients() -> int:
    """Every client in the table, grouped by whether it can be written."""
    writable = [c for c in CLIENTS if c.writable]
    manual = [c for c in CLIENTS if not c.writable]

    print("Clients Yieldpoint can configure for you:\n")
    for client in writable:
        note = f"  ({client.note})" if client.note else ""
        print(f"  {client.key:16} {client.label:24} {client.scope}-level{note}")

    if manual:
        print("\nClients configured in YAML or TOML — use --show and paste:\n")
        for client in manual:
            print(f"  {client.key:16} {client.label:24} {client.fmt.upper()}")

    print("""
  yieldpoint install-mcp --client cursor              write it
  yieldpoint install-mcp --client codex --show        print it instead
  yieldpoint install-mcp --client cursor --path FILE  any location you like

Not listed? Every MCP client takes the same stdio command. Print the snippet
with --show and paste it wherever that client keeps its servers, or point
--path at the file. `yieldpoint mcp` is the part that matters.

Vendors move these paths between releases, so treat the table as a convenience
rather than an authority.""")
    return EXIT_OK


def install_hook(args) -> int:
    path = Path(args.settings) if args.settings else Path(".claude/settings.json")
    path.parent.mkdir(parents=True, exist_ok=True)

    settings: dict = {}
    if path.is_file():
        try:
            settings = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"yieldpoint: cannot read {path}: {exc}", file=sys.stderr)
            return EXIT_ERROR
        backup = path.with_suffix(path.suffix + ".yieldpoint-backup")
        backup.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        print(f"backed up existing settings to {backup}")

    # Resolved rather than hard-coded: a hook registered as a bare "yieldpoint"
    # that is not on the editor's PATH fails on every edit, and the failure
    # surfaces as a hook error rather than as a missing install.
    command = command_line("hook") + (" --advisory" if args.advisory else "")
    entry = {"matcher": HOOK_MATCHER, "hooks": [{"type": "command", "command": command}]}

    hooks = settings.setdefault("hooks", {})
    _register(hooks, "PreToolUse", entry)
    _verify_each_turn(hooks, advisory=args.advisory,
                      report=not getattr(args, "no_report", False))
    if getattr(args, "compact", False):
        _compact_tool_output(hooks)

    path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    mode = "advisory" if args.advisory else "blocking"
    print(f"registered '{command}' on {HOOK_MATCHER} in {path} ({mode} mode)")
    print(f"registered '{command_line('hook', '--stop')}' on Stop, which catches")
    print("  edits made through the shell — the per-edit gate above cannot see those")
    if not getattr(args, "no_report", False):
        print(f"registered '{command_line('report')}' on Stop, so "
              ".yieldpoint/report.html")
        print("  refreshes at the end of every turn")
    _gate_alongside(Path(getattr(args, "root", None) or "."),
                    bool(getattr(args, "no_git", False)))
    print("Restart Claude Code, or start a new session, for it to take effect.")
    return EXIT_OK


#: Marks the script as ours, so re-installing replaces it and a hand-written
#: one is never overwritten without being backed up first.
GIT_MARKER = "# installed by yieldpoint"

GIT_GATE = """#!/bin/sh
{marker}
# The provider-independent gate. Editor hooks belong to one editor and see only
# that editor's edit tools; a commit is where every agent's work arrives,
# whichever tool wrote it and whichever model drove it. Remove this file to
# uninstall.
command -v {executable} >/dev/null 2>&1 || {{
  echo "yieldpoint: {executable} not found — commit allowed, nothing verified" >&2
  exit 0
}}
{invocation} review --staged
status=$?
# 0 clean, 1 findings, 3 nothing analysable. Only findings refuse: a commit
# blocked because no rule understood the language is a gate people delete.
[ "$status" -eq 1 ] && exit 1
exit 0
"""


def install_git_gate(root: Path) -> tuple[Path | None, str]:
    """Write ``.git/hooks/pre-commit``. Returns the path and what happened."""
    git = root / ".git"
    if git.is_file():  # a worktree: .git is a file pointing at the real directory
        try:
            pointer = git.read_text(encoding="utf-8").split("gitdir:", 1)[1].strip()
            git = Path(pointer)
        except (OSError, IndexError):
            return None, "cannot resolve the worktree's git directory"
    if not git.is_dir():
        return None, "not a git repository — nothing to gate commits with"

    hooks = git / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    path = hooks / "pre-commit"

    note = "wrote"
    if path.exists():
        existing = path.read_text(encoding="utf-8", errors="replace")
        if GIT_MARKER in existing:
            note = "replaced"
        else:
            backup = path.with_suffix(".yieldpoint-backup")
            backup.write_text(existing, encoding="utf-8")
            note = f"replaced (yours backed up to {backup})"

    from .mcp.clients import command_argv

    executable, _ = command_argv()
    path.write_text(
        GIT_GATE.format(marker=GIT_MARKER, executable=executable,
                        invocation=command_line()),
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path, note




def init(args) -> int:
    """Wire up everything in one command: config, MCP server, and the hook.

    Three separate commands is three chances to stop halfway, and the half that
    usually gets skipped is the hook — which is the only one that enforces
    anything. Advisory by default, because a gate that blocks on its first run
    in an unfamiliar repository gets uninstalled rather than tuned.
    """
    root = Path(args.root or ".")
    print(f"Setting up Yieldpoint in {root.resolve()}\n")

    config = root / ".yieldpoint.json"
    if config.is_file():
        print(f"  config   {config} already exists, left alone")
    else:
        config.write_text(json.dumps(STARTER_CONFIG, indent=2) + "\n", encoding="utf-8")
        print(f"  config   wrote {config}")

    client = BY_KEY.get(args.client or "claude-code")
    if client is None:
        print(f"yieldpoint: unknown client {args.client!r}; try install-mcp --list",
              file=sys.stderr)
        return EXIT_ERROR
    try:
        path, _backup = install_client(client, root)
        print(f"  mcp      registered for {client.label} in {path}")
    except OSError as exc:
        print(f"  mcp      could not write configuration: {exc}", file=sys.stderr)

    _report_git_gate(root, skip=bool(getattr(args, "no_git", False)))

    hooked = client.key == "claude-code" and not args.no_hook
    if args.no_hook:
        print("  hook     skipped (--no-hook); nothing will enforce, only explain")
    elif not hooked:
        print(f"  hook     no native hook for {client.label}; MCP advises and git gates commits")
    else:
        hook_args = _HookArgs(
            settings=str(root / ".claude" / "settings.json"),
            advisory=not args.enforce,
            no_report=bool(getattr(args, "no_report", False)),
        )
        install_hook(hook_args)

    _next_steps(args.enforce, hooked)
    return EXIT_OK


def _gate_alongside(root: Path, skip: bool) -> None:
    """Install the commit gate beside whatever else was just installed.

    Every install route ends here, because the editor hook and the MCP server
    both stop at the edge of the editor. Work arrives by other doors — a shell
    script, a rebase, a teammate's branch — and only the commit gate sees
    those. Installing the part that explains without the part that enforces is
    how a project ends up believing it is covered.
    """
    if skip:
        print("  git      skipped (--no-git); commits are not gated")
        return
    gate, note = install_git_gate(root)
    if gate is None:
        print(f"  git      no commit gate: {note}")
    else:
        print(f"  git      {note} {gate}")


def _report_git_gate(root: Path, *, skip: bool) -> None:
    """Install the commit gate and say what happened, in init's voice."""
    if skip:
        print("  git      skipped (--no-git); commits are not gated")
        return
    gate, note = install_git_gate(root)
    if gate is None:
        print(f"  git      {note}")
        return
    print(f"  git      {note} {gate}")
    print("           every provider's work passes through a commit, so this")
    print("           gate holds for agents with no editor hook at all")


def _next_steps(enforce: bool, hooked: bool) -> None:
    """What to do now. Separated so ``init`` stays readable as a sequence."""
    print("\nThree doors, deliberately:" if hooked else "\nTwo doors, deliberately:")
    if hooked:
        print("  per-edit hook   catches an edit before it lands — Claude Code only,")
        print("                  and only for edits made with its file-edit tools")
        print("  Stop gate       catches everything that hook cannot see, including")
        print("                  edits written through the shell")
    print("  pre-commit      holds for every other provider, because a commit is")
    print("                  where all of their work arrives")

    print("\nNext:")
    print("  1. RESTART your editor, or start a new session.")
    print("     Hooks and MCP servers are read when a session starts, so")
    print("     nothing you just installed is active in this one — and that")
    print("     looks exactly like it working: no output, every edit allowed.")
    print("  2. yieldpoint doctor        # confirms each door has actually run")
    print("  3. yieldpoint review        # works right now, no restart needed")
    if not enforce and hooked:
        print("\nThe hook is advisory: it reports and never blocks. Re-run with")
        print("  yieldpoint init --enforce   once you are happy with what it reports.")


@dataclass
class _HookArgs:
    """The arguments ``install_hook`` reads, so ``init`` can call it directly."""

    settings: str
    advisory: bool
    no_report: bool = False


# ------------------------------------------------------------------- helpers



def _is_yieldpoint(entry: object) -> bool:
    if not isinstance(entry, dict):
        return False
    return any(
        isinstance(h, dict) and "yieldpoint" in str(h.get("command", ""))
        for h in entry.get("hooks", [])
    )
