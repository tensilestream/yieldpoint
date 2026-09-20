"""CLI and SDK delivery of compact tool output, with content-free accounting."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .context import compact_json
from .core.policy import Policy
from .ledger import Event, identity, record
from .recording import enabled, path_for


def compact_and_record(text: str, *, root=".", policy=None,
                       count_tokens=None, tokenizer=""):
    """Compact before inserting tool output into a prompt. Returns (result, recorded).

    Recording counts generated output, not proof that a model consumed it. Text
    and tool arguments are never stored in the ledger.
    """
    resolved = Policy.load(policy, root=root)
    result = compact_json(text, count_tokens=count_tokens, tokenizer=tokenizer)
    recorded = False
    if enabled(resolved):
        run, agent = identity()
        recorded = record(Event(surface="compact", status="compacted", run=run,
                                agent=agent, context=result.metrics()),
                          path_for(resolved, root))
    return result, recorded


def compact_command(args) -> int:
    try:
        text = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8")
        result, recorded = compact_and_record(text, root=args.root, policy=args.policy)
    except (OSError, ValueError, UnicodeError) as exc:
        print(f"yieldpoint: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({"text": result.text, "metrics": result.metrics(), "recorded": recorded}))
    else:
        sys.stdout.write(result.text)
    return 0


def add_command(sub) -> None:
    command = sub.add_parser("compact", help="losslessly compact JSON tool output before a model reads it")
    command.add_argument("input", nargs="?", default="-", help="JSON file or - for stdin")
    command.add_argument("--root", default=".")
    command.add_argument("--policy", default=None)
    command.add_argument("--json", action="store_true", help="return output and accounting metadata")
    command.set_defaults(handler=compact_command)
