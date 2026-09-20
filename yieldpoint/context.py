"""Lossless JSON tool-output compaction, before an agent reads the output.

Only insignificant JSON whitespace is removed. Strings, number lexemes, key
order and duplicate keys are preserved. This is not transcript summarisation.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable

from .compaction import estimate_tokens

_PARTS = re.compile(r'"(?:\\.|[^"\\])*"|[ \t\r\n]+')


@dataclass(frozen=True)
class Context:
    text: str
    input_chars: int
    output_chars: int
    input_bytes: int
    output_bytes: int
    input_tokens: int
    output_tokens: int
    tokenizer: str = ""

    def metrics(self) -> dict:
        return {
            "method": "json-whitespace-v1",
            "input_chars": self.input_chars, "output_chars": self.output_chars,
            "input_bytes": self.input_bytes, "output_bytes": self.output_bytes,
            "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
            "tokenizer": self.tokenizer,
        }


def _reject_unusable(text, count_tokens, tokenizer: str) -> None:
    """Refuse arguments that would make the reported numbers unsafe to trust.

    Invalid JSON is rejected rather than passed through: a compactor that
    silently returns its input looks identical to one that worked.
    """
    if not isinstance(text, str):
        raise ValueError("text must be a JSON string")
    if bool(count_tokens) != bool(tokenizer) or len(tokenizer) > 128:
        raise ValueError("provide both count_tokens and a tokenizer name (up to 128 characters)")
    try:
        # Validate without converting numbers, which can round or overflow.
        json.loads(text, parse_int=str, parse_float=str, parse_constant=_invalid_constant)
    except (ValueError, RecursionError) as exc:
        raise ValueError(f"cannot compact invalid JSON: {exc}") from exc


def _counts(text: str, output: str, count_tokens) -> tuple[int, int]:
    """Input and output token counts, from the supplied counter or the estimate."""
    counter = count_tokens or (lambda value: estimate_tokens(len(value)))
    before, after = counter(text), counter(output)
    if any(type(value) is not int or value < 0 for value in (before, after)):
        raise ValueError("tokenizer must return non-negative integer counts")
    return before, after


def _strip(match) -> str:
    """Drop whitespace, keep string literals exactly as written."""
    return match[0] if match[0].startswith('"') else ""


def compact_json(text: str, *, count_tokens: Callable[[str], int] | None = None,
                 tokenizer: str = "") -> Context:
    """Return a smaller representation, with no model or filesystem access.

    Supply a tokenizer callback and its name for measured token counts. Without
    one, counts are estimates. Neither mode measures provider-billed savings.
    If the tokenizer reports expansion, retain the original input.
    """
    _reject_unusable(text, count_tokens, tokenizer)
    output = _PARTS.sub(_strip, text)
    before, after = _counts(text, output, count_tokens)
    if after > before:
        output, after = text, before
    return Context(output, len(text), len(output), len(text.encode("utf-8")),
                   len(output.encode("utf-8")), before, after, tokenizer)


def _invalid_constant(value: str):
    raise ValueError(f"non-JSON constant: {value}")


__all__ = ["Context", "compact_json"]
