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
    hook_command,
    linters_command,
    scan_command,
)
from .reports import (
    backtest_command, doctor_command, export_command, report_command,
    stats_command,
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
    review_cmd.add_argument("--policy", default=None, help="path to .yieldpoint.json")
    review_cmd.add_argument("--json", action="store_true", help="machine-readable output")
    review_cmd.set_defaults(handler=review_command)

    doctor_cmd = sub.add_parser(
        "doctor", help="check that Yieldpoint is actually working")
    doctor_cmd.add_argument("--root", default=".", help="project directory")
    doctor_cmd.set_defaults(handler=doctor_command)

    backtest_cmd = sub.add_parser(
        "backtest", help="replay history: what would this have flagged?")
    backtest_cmd.add_argument("--since", default="HEAD~50",
                              help="range start, e.g. HEAD~200 or a tag")
    backtest_cmd.add_argument("--root", default=".", help="repository directory")
    backtest_cmd.add_argument("--limit", type=int, default=500,
                              help="maximum commits to replay")
    backtest_cmd.add_argument("--policy", default=None, help="path to .yieldpoint.json")
    backtest_cmd.add_argument("--json", action="store_true", help="machine-readable")
    backtest_cmd.set_defaults(handler=backtest_command)

    _add_report_command(sub)
    _add_export_command(sub)
    stats_cmd = sub.add_parser(
        "stats", help="what Yieldpoint has caught, and what it cost")
    stats_cmd.add_argument("--root", default=".", help="project directory")
    stats_cmd.add_argument("--policy", default=None, help="path to .yieldpoint.json")
    stats_cmd.add_argument(
        "--price", type=float, default=None, metavar="PER_M",
        help="input-token price per million, for a cost estimate; "
             "overrides metrics.price_per_million")
    stats_cmd.add_argument(
        "--html", nargs="?", const="", default=None, metavar="PATH",
        help="write the HTML report instead of printing; "
             "defaults to .yieldpoint/report.html")
    stats_cmd.add_argument(
        "--since", default="", metavar="PERIOD",
        help="only this period: 2h, 30m, 7d, today, or session (last 8h)")
    stats_cmd.add_argument("--run", default="", help="only this YIELDPOINT_RUN_ID")
    stats_cmd.add_argument("--agent", default="", help="only this YIELDPOINT_AGENT")
    stats_cmd.add_argument("--json", action="store_true", help="machine-readable output")
    stats_cmd.set_defaults(handler=stats_command)

def _add_export_command(sub) -> None:
    """Getting the numbers off this machine, without this package doing it."""
    export_cmd = sub.add_parser(
        "export", help="stream the ledger as JSON Lines, or run the configured sink")
    export_cmd.add_argument(
        "--sink", action="store_true",
        help="hand new events to metrics.sink instead of writing to stdout")
    export_cmd.add_argument("--root", default=".", help="project directory")
    export_cmd.add_argument("--since", default="", metavar="PERIOD",
                            help="only this period: 2h, 30m, 7d, today, or session")
    export_cmd.add_argument("--run", default="", help="only this YIELDPOINT_RUN_ID")
    export_cmd.add_argument("--agent", default="", help="only this YIELDPOINT_AGENT")
    export_cmd.add_argument("--policy", default=None, help="path to .yieldpoint.json")
    export_cmd.set_defaults(handler=export_command)


def _add_report_command(sub) -> None:
    """The HTML page. Its own function only because the parser it belongs to
    was over the length limit this project enforces on everyone else."""
    report_cmd = sub.add_parser(
        "report", help="write a self-contained HTML page from the ledger")
    report_cmd.add_argument(
        "--out", default="", metavar="FILE",
        help="where to write it (default: .yieldpoint/report.html, which is "
             "ignored by git and refreshed in place)")
    report_cmd.add_argument("--root", default=".", help="project directory")
    report_cmd.add_argument("--since", default="", metavar="PERIOD",
                            help="2h, 30m, 7d, today, or session")
    report_cmd.add_argument("--run", default="", help="only this YIELDPOINT_RUN_ID")
    report_cmd.add_argument("--agent", default="", help="only this YIELDPOINT_AGENT")
    report_cmd.add_argument("--policy", default=None, help="path to .yieldpoint.json")
    report_cmd.set_defaults(handler=report_command)


def _add_setup_commands(sub) -> None:
    """Subcommands that wire Yieldpoint into something else rather than run it.

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
    init_cmd.add_argument(
        "--no-git", action="store_true",
        help="do not install the .git/hooks/pre-commit gate")
    init_cmd.add_argument(
        "--no-report", action="store_true",
        help="do not refresh .yieldpoint/report.html at the end of each turn")
    init_cmd.set_defaults(handler=init)

    mcp_cmd = sub.add_parser("mcp", help="run the MCP server on stdio")
    mcp_cmd.add_argument("--policy", help="path to .yieldpoint.json")
    mcp_cmd.set_defaults(handler=mcp_command)

    mcp_install = sub.add_parser("install-mcp", help="register the MCP server with an editor")
    mcp_install.add_argument("--client", help="claude-code, cursor, vscode, ...")
    mcp_install.add_argument("--list", action="store_true", help="list supported clients")
    mcp_install.add_argument("--show", action="store_true", help="print the snippet, do not write")
    mcp_install.add_argument(
        "--path", default=None, help="write to this file instead of the known location")
    mcp_install.set_defaults(handler=install_mcp)

    install_cmd = sub.add_parser("install-hook", help="register the hook in .claude/settings.json")
    install_cmd.add_argument(
        "--no-report", action="store_true",
        help="do not refresh .yieldpoint/report.html at the end of each turn")
    install_cmd.add_argument("--settings", help="settings file (default: .claude/settings.json)")
    install_cmd.add_argument("--advisory", action="store_true", help="install in advisory mode")
    install_cmd.set_defaults(handler=install_hook)

#: Commands that speak a protocol or are consumed by another program. A banner
#: on any of these corrupts what the caller is reading, so they never get one
#: whatever the terminal says.
_MACHINE_COMMANDS = frozenset({"mcp", "hook"})


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if not getattr(args, "handler", None):
        parser.print_help()
        return EXIT_ERROR

    _greet(args)
    try:
        return args.handler(args)
    except KeyboardInterrupt:
        return EXIT_ERROR


def _greet(args) -> None:
    """Show the mark, when a person is the one reading.

    Suppressed for machine-facing commands and for ``--json``, and by the
    terminal checks in branding.py. Never printed to stdout — that carries
    results, and a decorated result is an unparseable one.
    """
    from .branding import show

    if args.command in _MACHINE_COMMANDS or getattr(args, "json", False):
        return
    show(args.command or "")


def _add_gate_commands(sub) -> None:
    """The commands a gate runs: the hook, and the two audits beside it."""
    hook_cmd = sub.add_parser("hook", help="run as a Claude Code hook (reads stdin)")
    hook_cmd.add_argument("--policy", help="path to .yieldpoint.json")
    hook_cmd.add_argument(
        "--stop", action="store_true",
        help="run as a Stop hook: verify the whole working tree, whatever edited it")
    hook_cmd.add_argument("--root", default=".", help="repository directory (with --stop)")
    hook_cmd.add_argument(
        "--json-decision", action="store_true",
        help="emit a structured permission decision instead of exiting non-zero")
    hook_cmd.add_argument(
        "--advisory", action="store_true",
        help="report findings but never deny an edit")
    hook_cmd.set_defaults(handler=hook_command)

    scan_cmd = sub.add_parser("scan", help="audit a repository as it stands")
    scan_cmd.add_argument("path", nargs="?", default=".", help="directory or file to audit")
    scan_cmd.add_argument("--policy", help="path to .yieldpoint.json")
    scan_cmd.add_argument("--json", action="store_true", help="emit the verdict as JSON")
    scan_cmd.add_argument("--rule", action="append", help="only report this rule (repeatable)")
    scan_cmd.set_defaults(handler=scan_command)

    linters_cmd = sub.add_parser("linters", help="list the linters this build can run")
    linters_cmd.add_argument("--policy", help="path to .yieldpoint.json")
    linters_cmd.set_defaults(handler=linters_command)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yieldpoint",
        description="Deterministic verification for agents that write code.",
    )
    parser.add_argument("--version", action="version", version=f"yieldpoint {__version__}")
    sub = parser.add_subparsers(dest="command")

    check_cmd = sub.add_parser("check", help="verify a change: a file transition or a diff")
    check_cmd.add_argument("--path", help="repository-relative path being changed")
    check_cmd.add_argument("--diff", help="unified diff covering a change set ('-' for stdin)")
    check_cmd.add_argument("--root", default=".", help="directory the diff's paths are relative to")
    check_cmd.add_argument("--before", help="file holding the previous content ('-' for stdin)")
    check_cmd.add_argument("--after", help="file holding the proposed content ('-' for stdin)")
    check_cmd.add_argument("--policy", help="path to .yieldpoint.json (default: discover upward)")
    check_cmd.add_argument("--json", action="store_true", help="emit the verdict as JSON")
    check_cmd.add_argument("--speak", action="store_true",
                       help="render for a listener, with voice-mode severity")
    check_cmd.set_defaults(handler=check)

    _add_reporting_commands(sub)


    _add_gate_commands(sub)

    _add_setup_commands(sub)

    return parser


# ------------------------------------------------------------------ commands


if __name__ == "__main__":
    sys.exit(main())
