"""Token accounting, and a test of the one assumption `yp stats` rests on.

`yieldpoint/ledger.py` sets CHARS_PER_TOKEN = 4 and labels every figure derived
from it an estimate, because pinning a real tokenizer would mean a dependency
and a false claim to precision. That is the honest choice, but it leaves the
constant unmeasured.

A benchmark run is in an unusual position to measure it: Ollama reports the
true token counts its tokenizer produced, and we have the exact text those
counts came from. That gives real (characters, tokens) pairs, so the constant
can be checked rather than assumed.

The measured ratio is model-specific and says nothing about any other
tokenizer. It is evidence about the size of the approximation, not a
replacement for it.
"""

from __future__ import annotations

from dataclasses import dataclass

from yieldpoint.ledger import CHARS_PER_TOKEN


@dataclass(frozen=True)
class Sample:
    """One observed pairing of text size against its true token count."""

    chars: int
    tokens: int


def ratio(samples: list[Sample]) -> float:
    """Characters per token across every sample, pooled rather than averaged.

    Pooled because a mean of per-sample ratios over-weights short texts, and
    the question is what a whole run costs, not what a typical message does.
    """
    total_tokens = sum(s.tokens for s in samples)
    if not total_tokens:
        return 0.0
    return sum(s.chars for s in samples) / total_tokens


def calibrate(samples: list[Sample], assumed: int = CHARS_PER_TOKEN) -> dict:
    """How far the stated approximation sits from this model's tokenizer."""
    measured = ratio(samples)
    if not measured:
        return {"samples": 0, "note": "no token counts reported by the daemon"}

    # A figure computed as chars/assumed relates to the true chars/measured
    # count by exactly this factor, so this *is* the error in the estimate —
    # not the gap between the two divisors, which is a different number.
    error = measured / assumed - 1.0
    return {
        "samples": len(samples),
        "total_chars": sum(s.chars for s in samples),
        "total_tokens": sum(s.tokens for s in samples),
        "measured_chars_per_token": round(measured, 3),
        "assumed_chars_per_token": assumed,
        "estimate_error": round(error, 3),
        "reading": _reading(error, assumed, measured),
    }


def _reading(error: float, assumed: int, measured: float) -> str:
    if abs(error) < 0.005:
        return (f"this model's tokenizer measured {measured:.2f} chars/token; "
                f"the assumed {assumed} matches it.")
    return (
        f"this model's tokenizer measured {measured:.2f} chars/token. A token "
        f"figure computed as characters/{assumed} is "
        f"{'too high' if error > 0 else 'too low'} by {abs(error):.0%} for this "
        f"model. Says nothing about any other tokenizer."
    )


def both_sides(prompt: list[Sample], output: list[Sample],
               assumed: int = CHARS_PER_TOKEN) -> dict:
    """Calibrate each side separately, because only one of them is clean.

    *Output* is the trustworthy measurement: the exact text the model generated
    (visible content plus any hidden reasoning) against the exact token count
    the daemon reported for generating it.

    *Prompt* is a lower bound, not a measurement. The daemon's
    ``prompt_eval_count`` includes chat-template scaffolding — role markers and
    special tokens — that never appears in the characters we can see, so the
    token side is inflated and the resulting chars-per-token reads low.

    `yp stats` estimates the *input* an LLM judge would read, so the prompt side
    is the relevant comparison, and its bias direction matters: it understates
    chars per token, which overstates the token estimate.
    """
    out = calibrate(output, assumed)
    inp = calibrate(prompt, assumed)
    inp["caveat"] = (
        "lower bound: prompt_eval_count includes chat-template tokens that are "
        "not in the characters counted, so true chars/token is at least this."
    )
    return {"output": out, "prompt": inp}


def totals(prompt: list[Sample], output: list[Sample]) -> dict:
    """What one arm actually spent, from the daemon's own counters."""
    return {
        "prompt_tokens": sum(s.tokens for s in prompt),
        "output_tokens": sum(s.tokens for s in output),
        "total_tokens": sum(s.tokens for s in prompt + output),
        "prompt_chars": sum(s.chars for s in prompt),
        "output_chars": sum(s.chars for s in output),
    }
