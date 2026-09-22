"""The shape every ledger-reading command has.

`trend`, `adoption`, and anything that follows them all do the same four
things: load the policy, fold the ledger, render or serialise, exit. Written
out three times they drifted immediately — one grew a `--json` flag the others
did not, and `duplicate_across_files` said so before a second reader ever saw
them.

The rendering and the fold stay in their own modules; only the plumbing lives
here. What a command *means* is worth reading twice, how it reaches stdout is
not.
"""

from __future__ import annotations

import json
import sys

EXIT_OK, EXIT_ERROR = 0, 2


def run(args, fold, render, to_dict) -> int:
    """Load the ledger, fold it, and print it however it was asked for."""
    from .core.policy import Policy
    from .ledger import load
    from .recording import path_for

    try:
        policy = Policy.load(args.policy, root=args.root)
        folded = fold(load(path_for(policy, args.root)))
    except (OSError, ValueError) as exc:
        print(f"yieldpoint: {exc}", file=sys.stderr)
        return EXIT_ERROR
    print(json.dumps(to_dict(folded), indent=2) if args.json else render(folded))
    return EXIT_OK


def register(sub, name: str, help_text: str, handler):
    """Add one ledger-reading command, with the flags they all share."""
    command = sub.add_parser(name, help=help_text)
    command.add_argument("--root", default=".")
    command.add_argument("--policy", default=None)
    command.add_argument("--json", action="store_true")
    command.set_defaults(handler=handler)
    return command


__all__ = ["run", "register"]
