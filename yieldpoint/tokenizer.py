"""An optional, named token counter. Off by default.

Every token figure this package prints without one of these is a
four-characters-per-token estimate, and is labelled as one. This module lets a
repository opt into a real counter and have the result filed under the name of
the tokenizer that produced it — two tokenizers disagree about the same text,
so a total spanning both is a number neither would confirm.

Four things it deliberately does not do:

- It does not ship a tokenizer. The verification core keeps no runtime
  dependencies (RULES.md section 3), so the counter is an extra you install.
- It does not choose one for you. ``metrics.tokenizer`` is empty by default,
  which means a default install measures nothing and says so.
- It does not reach the network on its own behalf. Nothing here is consulted
  unless a policy names a tokenizer; note that the *first* use of a tiktoken
  encoding downloads its vocabulary, which is why this is opt-in rather than
  a default.
- It does not measure what a provider bills. A named tokenizer measures that
  tokenizer. Prompt caching, tool-call overhead and retries all sit outside it,
  and ``contextstats`` keeps reporting provider savings as unknown.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

#: ``<provider>:<encoding>``, e.g. ``tiktoken:o200k_base``. The whole string is
#: recorded, so a figure can always be traced to what produced it.
SEPARATOR = ":"


@dataclass(frozen=True)
class Counter:
    """A token counter and the name it must be reported under."""

    name: str
    count: Callable[[str], int]


def _tiktoken(encoding: str) -> Callable[[str], int] | None:
    try:
        import tiktoken
    except ImportError:
        return None
    try:
        encoder = tiktoken.get_encoding(encoding)
    except (ValueError, KeyError, OSError):
        return None
    return lambda text: len(encoder.encode(text, disallowed_special=()))


#: Providers this build knows how to load. Adding one is a line here and an
#: entry in the optional dependencies, not a change to any caller.
PROVIDERS: dict[str, Callable[[str], Callable[[str], int] | None]] = {
    "tiktoken": _tiktoken,
}


def resolve(spec: str) -> Counter | None:
    """A counter for ``provider:encoding``, or ``None`` if it cannot be had.

    Returning ``None`` is a normal outcome, not an error: the caller keeps
    estimating and keeps saying that it is estimating. Failing loudly here
    would turn a missing optional extra into a broken install.
    """
    provider, _, encoding = spec.strip().partition(SEPARATOR)
    load = PROVIDERS.get(provider.lower())
    if not load or not encoding:
        return None
    count = load(encoding)
    return Counter(spec.strip(), count) if count else None


__all__ = ["Counter", "PROVIDERS", "resolve"]
