"""Command line interface.

The CLI is a first-class surface, not a convenience: it is how every language
that is not Python consumes this engine. ``--json`` emits the versioned verdict
schema from verdict.py, so a binding in any language is a subprocess call and a
JSON parse.

Exit codes: ``0`` clean, ``1`` findings, ``2`` usage or input error.
"""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .commands import (
    EXIT_ERROR,
    EXIT_FINDINGS,
    EXIT_UNVERIFIED,
    EXIT_OK,
    check,
    check_diff,
    review_command,
    stats_command,
    hook_command,
    linters_command,
    scan_command,
)
from .install import HOOK_MATCHER, init, install_hook, install_mcp, mcp_command

#: The shell contract is part of this module's API, so it is declared explicitly
#: — an export the `export_removed` rule can then protect.
__all__ = ["main", "EXIT_OK", "EXIT_FINDINGS", "EXIT_UNVERIFIED", "EXIT_ERROR"]




def _add_reporting_commands(sub) -> None:
    """Subcommands that answer "what happened?" rather than verify a change."""
    review_cmd = sub.add_parser(
        "review", help="verify uncommitted work — no arguments needed")
    review_cmd.add_argument("--root", default=".", help="repository directory")
    review_cmd.add_argument("--staged", action="store_true", help="only what is staged")
    review_cmd.add_argument(
        "--against", default="", help="compare with a branch or commit instead")
    review_cmd.add_argument("--policy", default=None, help="path to .aegisflow.json")
    review_cmd.add_argument("--json", action="store_true", help="machine-readable output")
    review_cmd.set_defaults(handler=review_command)

    stats_cmd = sub.add_parser(
        "stats", help="what AegisFlow has caught, and what it cost")
    stats_cmd.add_argument("--root", default=".", help="project directory")
    stats_cmd.add_argument("--policy", default=None, help="path to .aegisflow.json")
    stats_cmd.add_argument("--json", action="store_true", help="machine-readable output")
    stats_cmd.set_defaults(handler=stats_command)

def _add_setup_commands(sub) -> None:
    """Subcommands that wire AegisFlow into something else rather than run it.

    Split out of ``_parser`` for one reason: it was over the length limit this
    project enforces on everyone else, and these four belong together.
    """
    init_cmd = sub.add_parser(
        "init", help="set up config, MCP server and hook in one command")
    init_cmd.add_argument("--root", default=".", help="project directory")
    init_cmd.add_argument("--client", default="claude-code", help="editor to register with")
    init_cmd.add_argument(
        "--enforce", action="store_true", help="hook blocks instead of only reporting")
    init_cmd.add_argument("--no-hook", action="store_true", help="MCP only, no enforcement")
    init_cmd.set_defaults(handler=init)

    mcp_cmd = sub.add_parser("mcp", help="run the MCP server on stdio")
    mcp_cmd.add_argument("--policy", help="path to .aegisflow.json")
    mcp_cmd.set_defaults(handler=mcp_command)

    mcp_install = sub.add_parser("install-mcp", help="register the MCP server with an editor")
    mcp_install.add_argument("--client", help="claude-code, cursor, vscode, ...")
    mcp_install.add_argument("--list", action="store_true", help="list supported clients")
    mcp_install.add_argument("--show", action="store_true", help="print the snippet, do not write")
    mcp_install.set_defaults(handler=install_mcp)

    install_cmd = sub.add_parser("install-hook", help="register the hook in .claude/settings.json")
    install_cmd.add_argument("--settings", help="settings file (default: .claude/settings.json)")
    install_cmd.add_argument("--advisory", action="store_true", help="install in advisory mode")
    install_cmd.set_defaults(handler=install_hook)

def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if not getattr(args, "handler", None):
        parser.print_help()
        return EXIT_ERROR
    try:
        return args.handler(args)
    except KeyboardInterrupt:
        return EXIT_ERROR


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aegisflow",
        description="Deterministic verification for agents that write code.",
    )
    parser.add_argument("--version", action="version", version=f"aegisflow {__version__}")
    sub = parser.add_subparsers(dest="command")

    check_cmd = sub.add_parser("check", help="verify a change: a file transition or a diff")
    check_cmd.add_argument("--path", help="repository-relative path being changed")
    check_cmd.add_argument("--diff", help="unified diff covering a change set ('-' for stdin)")
    check_cmd.add_argument("--root", default=".", help="directory the diff's paths are relative to")
    check_cmd.add_argument("--before", help="file holding the previous content ('-' for stdin)")
    check_cmd.add_argument("--after", help="file holding the proposed content ('-' for stdin)")
    check_cmd.add_argument("--policy", help="path to .aegisflow.json (default: discover upward)")
    check_cmd.add_argument("--json", action="store_true", help="emit the verdict as JSON")
    check_cmd.add_argument("--speak", action="store_true",
                       help="render for a listener, with voice-mode severity")
    check_cmd.set_defaults(handler=check)

    _add_reporting_commands(sub)


    hook_cmd = sub.add_parser("hook", help="run as a Claude Code PreToolUse hook (reads stdin)")
    hook_cmd.add_argument("--policy", help="path to .aegisflow.json")
    hook_cmd.add_argument(
        "--json-decision", action="store_true",
        help="emit a structured permission decision instead of exiting non-zero")
    hook_cmd.add_argument(
        "--advisory", action="store_true",
        help="report findings but never deny an edit")
    hook_cmd.set_defaults(handler=hook_command)

    scan_cmd = sub.add_parser("scan", help="audit a repository as it stands")
    scan_cmd.add_argument("path", nargs="?", default=".", help="directory or file to audit")
    scan_cmd.add_argument("--policy", help="path to .aegisflow.json")
    scan_cmd.add_argument("--json", action="store_true", help="emit the verdict as JSON")
    scan_cmd.add_argument("--rule", action="append", help="only report this rule (repeatable)")
    scan_cmd.set_defaults(handler=scan_command)

    linters_cmd = sub.add_parser("linters", help="list the linters this build can run")
    linters_cmd.add_argument("--policy", help="path to .aegisflow.json")
    linters_cmd.set_defaults(handler=linters_command)

    _add_setup_commands(sub)

    return parser


# ------------------------------------------------------------------ commands


if __name__ == "__main__":
    sys.exit(main())
