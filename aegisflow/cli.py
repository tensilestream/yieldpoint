"""Command line interface.

The CLI is a first-class surface, not a convenience: it is how every language
that is not Python consumes this engine. ``--json`` emits the versioned verdict
schema from verdict.py, so a binding in any language is a subprocess call and a
JSON parse.

Exit codes: ``0`` clean, ``1`` findings, ``2`` usage or input error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .core.policy import Policy
from .core.verdict import Status, Verdict
from .hook import blocks, decision_json, evaluate, read_payload, render
from .verify import verify_change

EXIT_OK, EXIT_FINDINGS, EXIT_ERROR = 0, 1, 2

HOOK_MATCHER = "Edit|MultiEdit|Write"


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

    check = sub.add_parser("check", help="verify one file's before/after transition")
    check.add_argument("--path", required=True, help="repository-relative path being changed")
    check.add_argument("--before", help="file holding the previous content ('-' for stdin)")
    check.add_argument("--after", help="file holding the proposed content ('-' for stdin)")
    check.add_argument("--policy", help="path to .aegisflow.json (default: discover upward)")
    check.add_argument("--json", action="store_true", help="emit the verdict as JSON")
    check.set_defaults(handler=_check)

    hook = sub.add_parser("hook", help="run as a Claude Code PreToolUse hook (reads stdin)")
    hook.add_argument("--policy", help="path to .aegisflow.json")
    hook.add_argument(
        "--json-decision", action="store_true",
        help="emit a structured permission decision instead of exiting non-zero")
    hook.add_argument(
        "--advisory", action="store_true",
        help="report findings but never deny an edit")
    hook.set_defaults(handler=_hook)

    install = sub.add_parser("install-hook", help="register the hook in .claude/settings.json")
    install.add_argument("--settings", help="settings file (default: .claude/settings.json)")
    install.add_argument("--advisory", action="store_true", help="install in advisory mode")
    install.set_defaults(handler=_install_hook)

    return parser


# ------------------------------------------------------------------ commands


def _check(args) -> int:
    try:
        before = _read_source(args.before)
        after = _read_source(args.after)
    except OSError as exc:
        print(f"aegisflow: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if before is None and after is None:
        print("aegisflow: supply --before and/or --after", file=sys.stderr)
        return EXIT_ERROR

    try:
        policy = Policy.load(args.policy)
    except (OSError, ValueError) as exc:
        print(f"aegisflow: {exc}", file=sys.stderr)
        return EXIT_ERROR

    verdict = verify_change(before, after, args.path, policy)
    if args.json:
        print(verdict.to_json(indent=2))
    else:
        _print_human(verdict, policy)
    return EXIT_OK if verdict.status is Status.PASS else EXIT_FINDINGS


def _hook(args) -> int:
    payload = read_payload(sys.stdin.read())
    verdict, change = evaluate(payload, args.policy)

    if args.json_decision:
        print(decision_json(verdict, change))
        return EXIT_OK

    if verdict.status is Status.PASS or args.advisory:
        if verdict.findings:
            print(render(verdict, change), file=sys.stderr)
        return EXIT_OK

    if blocks(verdict):
        # Exit code 2 is the blocking signal; stderr is fed back to the agent.
        print(render(verdict, change), file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK


def _install_hook(args) -> int:
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


def _read_source(value: str | None) -> str | None:
    if value is None:
        return None
    if value == "-":
        return sys.stdin.read()
    return Path(value).read_text(encoding="utf-8")


def _print_human(verdict: Verdict, policy: Policy) -> None:
    for warning in policy.warnings:
        print(f"policy warning: {warning}", file=sys.stderr)
    for note in verdict.skipped:
        print(f"skipped: {note}", file=sys.stderr)

    if verdict.status is Status.PASS:
        if verdict.checked:
            print(f"ok  {', '.join(verdict.checked)}")
        elif not verdict.skipped:
            print("ok  nothing to check")
        return

    print(f"{verdict.status.value.upper()}  {len(verdict.findings)} finding(s)\n")
    for finding in verdict.findings:
        symbol = f" in {finding.symbol}" if finding.symbol else ""
        print(f"  {finding.file}:{finding.line}{symbol}  [{finding.rule}]")
        print(f"    {finding.detail}")
        print(f"    fix: {finding.prescription}\n")


if __name__ == "__main__":
    sys.exit(main())
