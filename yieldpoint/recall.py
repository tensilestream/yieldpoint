"""Keeping what a bounded result left out, so it can be asked for again.

Everything else this package writes is content-free by design: the ledger
records sizes and rule names and never the source. This module is the
exception, and it is opt-in for exactly that reason. A recoverable original
has to be stored somewhere, and storing tool output means writing whatever
that output contained — including whatever was in the file the tool read.

Two failure modes matter more than the saving:

- **A handle that cannot be resolved must say so.** Returning nothing, or
  returning what happens to be on disk under that name, would let a model
  believe it had recovered the omitted part. The omission would then be
  invisible again, which is the whole thing this is supposed to prevent.
- **Stored content must be verified, not trusted.** The handle is the digest
  of what was stored, so a file that no longer hashes to its own name is
  reported as unavailable rather than returned.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

#: Long enough that a collision is not a practical concern, short enough to
#: type back. The full digest is still what gets verified.
HANDLE_CHARS = 16

DIRECTORY = "recall"


class Unavailable(LookupError):
    """A handle names something this store cannot honestly produce."""


def _home(root: str | Path, policy) -> Path:
    """The store, beside the ledger it accompanies but never inside it."""
    return Path(policy.metrics.path).parent.joinpath(DIRECTORY) \
        if Path(policy.metrics.path).is_absolute() \
        else Path(root) / Path(policy.metrics.path).parent / DIRECTORY


def digest(text: str) -> str:
    """The handle for a piece of text. Same text, same handle, always."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:HANDLE_CHARS]


def keep(text: str, *, root: str | Path = ".", policy=None) -> str:
    """Store ``text`` and return its handle, or ``""`` if retention is off.

    An empty handle is a normal outcome and callers must cope with it: the
    disclosure line then says what was omitted without offering to fetch it,
    which is honest. Silently claiming a handle that stores nothing would not
    be.
    """
    if policy is None or not getattr(policy.metrics, "retain_omitted", False):
        return ""
    handle = digest(text)
    home = _home(root, policy)
    try:
        home.mkdir(parents=True, exist_ok=True)
        target = home / handle
        if not target.exists():
            target.write_text(text, encoding="utf-8")
    except OSError:
        return ""          # cannot store, so do not promise retrieval
    return handle


def recall(handle: str, *, root: str | Path = ".", policy=None) -> str:
    """The text a handle names, or ``Unavailable``. Never a partial answer."""
    if policy is None or not handle or "/" in handle or "\\" in handle:
        raise Unavailable(f"'{handle}' is not a handle this store issued")
    target = _home(root, policy) / handle
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise Unavailable(f"nothing stored under '{handle}': {exc}") from exc
    if digest(text) != handle:
        raise Unavailable(
            f"what is stored under '{handle}' no longer matches it; the "
            f"original cannot be produced and must not be guessed at")
    return text


def recall_command(args) -> int:
    """Hand back what a bounded result withheld, or say plainly that it cannot.

    Exits 2 on an unresolvable handle rather than printing nothing and exiting
    clean: a caller that cannot tell "here is the original" from "there is no
    original" is back to not knowing what it is missing.
    """
    import sys

    from .contextrecording import recall_and_record
    from .core.policy import Policy

    try:
        policy = Policy.load(args.policy, root=args.root)
        text = recall(args.handle, root=args.root, policy=policy)
    except (OSError, ValueError) as exc:
        print(f"yieldpoint: {exc}", file=sys.stderr)
        return 2
    except Unavailable as exc:
        print(f"yieldpoint: {exc}", file=sys.stderr)
        return 2
    recall_and_record(len(text), root=args.root, policy=policy)
    print(text)
    return 0


def add_command(sub) -> None:
    command = sub.add_parser(
        "recall", help="print the original a bounded result withheld")
    command.add_argument("handle", help="the handle named in the result")
    command.add_argument("--root", default=".")
    command.add_argument("--policy", default=None)
    command.set_defaults(handler=recall_command)


__all__ = ["DIRECTORY", "HANDLE_CHARS", "Unavailable", "add_command", "digest",
           "keep", "recall", "recall_command"]
