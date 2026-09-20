"""Accounting for generated compact output; never inferred provider savings."""
from __future__ import annotations

import math

_FIELDS = ("input_chars", "output_chars", "input_bytes", "output_bytes",
           "input_tokens", "output_tokens")


def valid(data) -> bool:
    return (isinstance(data, dict) and data.get("method") == "json-whitespace-v1"
            and isinstance(data.get("tokenizer"), str)
            and all(type(data.get(key)) is int and data[key] >= 0 for key in _FIELDS)
            and all(data[f"output_{unit}"] <= data[f"input_{unit}"]
                    for unit in ("chars", "bytes", "tokens")))


def _by_tokenizer(measured: list[dict]) -> dict:
    """Measured counts kept apart by the tokenizer that produced them.

    Two tokenizers disagree about the same text, so a single total across both
    is a number no tokenizer would confirm.
    """
    groups: dict[str, dict] = {}
    for record in measured:
        group = groups.setdefault(record["tokenizer"], {"operations": 0, "input_tokens": 0,
                                                        "output_tokens": 0, "tokens_removed": 0})
        group["operations"] += 1
        for key in ("input_tokens", "output_tokens"):
            group[key] += record[key]
        group["tokens_removed"] += record["input_tokens"] - record["output_tokens"]
    return groups


def _sizes(records: list[dict]) -> dict:
    """Character and byte totals, which no tokenizer choice can change."""
    return {
        "operations": len(records),
        "changed": sum(r["input_bytes"] > r["output_bytes"] for r in records),
        "input_chars": sum(r["input_chars"] for r in records),
        "output_chars": sum(r["output_chars"] for r in records),
        "input_bytes": sum(r["input_bytes"] for r in records),
        "output_bytes": sum(r["output_bytes"] for r in records),
    }


def _estimates(estimated: list[dict], price: float) -> dict:
    """The unmeasured remainder, labelled as an estimate rather than folded in."""
    token_delta = sum(r["input_tokens"] - r["output_tokens"] for r in estimated)
    return {"operations": len(estimated),
            "assumption": "4 characters per token, rounded up per output",
            "tokens_removed": token_delta, "price_per_million": price,
            "potential_input_cost_reduction": token_delta * price / 1_000_000 if price else None}


def summarise(events, price: float = 0.0) -> dict:
    if not math.isfinite(price) or price < 0:
        raise ValueError("price must be finite and non-negative")
    records = [e.context for e in events if valid(e.context)]
    return {
        **_sizes(records),
        "measured_tokens_by_tokenizer": _by_tokenizer([r for r in records if r["tokenizer"]]),
        "estimated": _estimates([r for r in records if not r["tokenizer"]], price),
        "provider_tokens_saved": None, "provider_cost_saved": None,
        "basis": "Generated JSON output only; not proof of prompt consumption. Excludes tool-call overhead, caching and retries.",
    }


def render(data: dict) -> str:
    if not data.get("operations"):
        return "CONTEXT COMPACTION — no operations recorded; provider savings unknown"
    removed = data["input_bytes"] - data["output_bytes"]
    estimate = data["estimated"]
    lines = ["CONTEXT COMPACTION — generated output, measured sizes",
             f"  {data['operations']:,} operations; {removed:,} bytes removed",
             f"  ~{estimate['tokens_removed']:,} tokens removed (4 chars/token estimate)"]
    for name, group in data["measured_tokens_by_tokenizer"].items():
        lines.append(f"  {group['tokens_removed']:,} tokens removed, measured by {name}")
    if estimate["potential_input_cost_reduction"] is not None:
        lines.append(f"  potential input cost reduction: ${estimate['potential_input_cost_reduction']:.6f} "
                     f"at ${estimate['price_per_million']:g}/M (estimated)")
    lines.append("  Provider-billed savings unknown. " + data["basis"])
    return "\n".join(lines)


def export_rows(events) -> list[dict]:
    """Both event kinds, preserving existing verification export fields."""
    from .timeline import timeline
    rows = [turn.to_dict() for turn in timeline(events)]
    rows.extend({"kind": "compaction", "at": event.at, "surface": event.surface,
                 "run": event.run, "agent": event.agent, "context": event.context}
                for event in events if valid(event.context))
    return sorted(rows, key=lambda row: (row["at"], row["surface"]))
