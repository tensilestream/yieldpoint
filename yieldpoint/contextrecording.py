"""CLI and SDK delivery of compact tool output, with content-free accounting."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .context import compact_json
from .tokenizer import resolve
from .core.policy import Policy
from .ledger import Event, identity, record
from .recording import Timer, enabled, path_for


def compact_and_record(text: str, *, root=".", policy=None,
                       count_tokens=None, tokenizer=""):
    """Compact before inserting tool output into a prompt. Returns (result, recorded).

    Recording counts generated output, not proof that a model consumed it. Text
    and tool arguments are never stored in the ledger.
    """
    resolved = Policy.load(policy, root=root)
    count_tokens, tokenizer = _counter(resolved, count_tokens, tokenizer)
    # Timed here rather than inside compact_json: reading a clock would make
    # that function's output depend on when it ran (RULES.md section 4).
    with Timer() as timer:
        result = compact_json(text, count_tokens=count_tokens, tokenizer=tokenizer)
    recorded = False
    if enabled(resolved):
        run, agent = identity()
        recorded = record(Event(surface="compact", status="compacted", run=run,
                                agent=agent,
                                context={**result.metrics(),
                                         "processing_ms": timer.elapsed_ms}),
                          path_for(resolved, root))
    return result, recorded


def _counter(policy, count_tokens, tokenizer: str):
    """The caller's counter, or the one this repository asked for.

    A policy that names an uninstallable tokenizer falls back to estimating
    and keeps labelling the result as an estimate; it never reports an
    estimated count under a tokenizer's name.
    """
    if count_tokens or tokenizer or not policy.metrics.tokenizer:
        return count_tokens, tokenizer
    counter = resolve(policy.metrics.tokenizer)
    return (counter.count, counter.name) if counter else (None, "")


BOUNDED_METHOD = "bounded-lines-v1"
RECALL_METHOD = "recall-v1"


def _sizes(before: str, after: str, method: str) -> dict:
    """Content-free accounting for one delivery, in the shape stats expects."""
    from .compaction import estimate_tokens
    return {"method": method,
            "input_chars": len(before), "output_chars": len(after),
            "input_bytes": len(before.encode("utf-8")),
            "output_bytes": len(after.encode("utf-8")),
            "input_tokens": estimate_tokens(len(before)),
            "output_tokens": estimate_tokens(len(after)),
            "tokenizer": ""}


def _store(context: dict, root, policy, surface: str) -> bool:
    resolved = Policy.load(policy, root=root)
    if not enabled(resolved):
        return False
    run, agent = identity()
    return record(Event(surface=surface, status="compacted", run=run,
                        agent=agent, context=context),
                  path_for(resolved, root))


def bound_and_record(result, *, root=".", policy=None) -> bool:
    """Account for a bounded delivery, including what it left out.

    ``omitted`` is recorded because the saving and the risk are the same
    number: those are the lines a reader did not see.
    """
    context = _sizes("x" * result.original_chars, result.text, BOUNDED_METHOD)
    context["omitted_lines"] = result.omitted
    context["kept_lines"] = result.kept
    return _store(context, root, policy, "bound")


def recall_and_record(chars: int, *, root=".", policy=None) -> bool:
    """Account for content handed back, which offsets an earlier saving."""
    return _store({"method": RECALL_METHOD, "chars_returned": chars},
                  root, policy, "recall")


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
