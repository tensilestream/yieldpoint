"""Accounting for generated compact output; never inferred provider savings."""
from __future__ import annotations

import math

_FIELDS = ("input_chars", "output_chars", "input_bytes", "output_bytes",
           "input_tokens", "output_tokens")

#: What each method guarantees. ``lossless`` is reversible in meaning: the same
#: JSON goes in and comes out, only insignificant whitespace is gone. A
#: ``bounded`` method decides what to leave out and must disclose it. The two
#: are reported apart and never summed — one number spanning both would mean
#: nothing, because they do not promise the same thing.
TIERS = {"json-whitespace-v1": "lossless", "bounded-lines-v1": "bounded"}

#: Records that add content back rather than removing it.
RECALL_METHOD = "recall-v1"


def valid_recall(data) -> bool:
    """A record of content handed back, which grows context rather than shrinking it."""
    return (isinstance(data, dict) and data.get("method") == RECALL_METHOD
            and type(data.get("chars_returned")) is int
            and data["chars_returned"] >= 0)


def known(data) -> bool:
    """Any context record this build can account for.

    The ledger rejects what it cannot account for, so a shape missing from here
    is not merely unreported — it is dropped on read while still sitting in the
    file. Every method that gets written must be recognised here.
    """
    return valid(data) or valid_recall(data)


def valid(data) -> bool:
    return (isinstance(data, dict) and data.get("method") in TIERS
            and isinstance(data.get("tokenizer"), str)
            and all(type(data.get(key)) is int and data[key] >= 0 for key in _FIELDS)
            and all(data[f"output_{unit}"] <= data[f"input_{unit}"]
                    for unit in ("chars", "bytes", "tokens")))


def _cost(tokens: int, price: float) -> float | None:
    """What those tokens would have cost to send, or nothing without a rate."""
    return tokens * price / 1_000_000 if price else None


def _by_tokenizer(measured: list[dict], price: float = 0.0) -> dict:
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
    for group in groups.values():
        group["potential_input_cost_reduction"] = _cost(group["tokens_removed"], price)
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
        "no_gain": sum(r["input_bytes"] <= r["output_bytes"] for r in records),
        "processing_ms": sum(int(r.get("processing_ms") or 0) for r in records),
        "by_tier": _by_tier(records),
    }


def _retrievals(events, records: list[dict]) -> dict:
    """What was handed back, set against what bounding saved.

    The honest test of a bounded result is not how much smaller it was. It is
    whether the bytes it withheld stayed withheld. Every retrieval returns the
    whole original, so a result retrieved once cost more than delivering it
    whole would have.
    """
    recalls = [e.context for e in events if valid_recall(e.context)]
    returned = sum(record["chars_returned"] for record in recalls)
    withheld = sum(r["input_chars"] - r["output_chars"] for r in records
                   if TIERS[r["method"]] == "bounded")
    return {"operations": len(recalls),
            "chars_returned": returned,
            "chars_withheld_by_bounding": withheld,
            "net_chars_withheld": withheld - returned}


def _by_tier(records: list[dict]) -> dict:
    """Bytes removed per guarantee, so the two are never added together."""
    tiers: dict[str, dict] = {}
    for record in records:
        tier = tiers.setdefault(TIERS[record["method"]],
                                {"operations": 0, "bytes_removed": 0})
        tier["operations"] += 1
        tier["bytes_removed"] += record["input_bytes"] - record["output_bytes"]
    return tiers


def _estimates(estimated: list[dict], price: float) -> dict:
    """The unmeasured remainder, labelled as an estimate rather than folded in."""
    token_delta = sum(r["input_tokens"] - r["output_tokens"] for r in estimated)
    return {"operations": len(estimated),
            "assumption": "4 characters per token, rounded up per output",
            "tokens_removed": token_delta, "price_per_million": price,
            "potential_input_cost_reduction": _cost(token_delta, price)}


def summarise(events, price: float = 0.0) -> dict:
    if not math.isfinite(price) or price < 0:
        raise ValueError("price must be finite and non-negative")
    records = [e.context for e in events if valid(e.context)]
    return {
        **_sizes(records),
        "retrievals": _retrievals(events, records),
        "measured_tokens_by_tokenizer": _by_tokenizer(
            [r for r in records if r["tokenizer"]], price),
        "estimated": _estimates([r for r in records if not r["tokenizer"]], price),
        "provider_tokens_saved": None, "provider_cost_saved": None,
        "basis": "Generated JSON output only; not proof of prompt consumption. Excludes tool-call overhead, caching and retries.",
    }


def _recalled(data: dict) -> list[str]:
    """Bounding's real score: what stayed withheld after every retrieval."""
    if not data.get("chars_withheld_by_bounding"):
        return []
    net = data["net_chars_withheld"]
    verdict = "net saving" if net > 0 else "net cost"
    return [f"  bounding withheld {data['chars_withheld_by_bounding']:,} chars; "
            f"{data['operations']:,} retrieval(s) returned "
            f"{data['chars_returned']:,}",
            f"    {abs(net):,} chars {verdict} after retrievals"]


def _spent(data: dict) -> list[str]:
    """Time spent compacting, distinguishing "too fast to measure" from unknown.

    The timer counts whole milliseconds, so a zero is sub-millisecond work and
    not an absence of measurement. Printing nothing would conflate the two.
    """
    if "processing_ms" not in data:
        return []
    spent = data["processing_ms"]
    return [f"  {spent:,} ms spent compacting" if spent
            else "  under 1 ms spent compacting, in total"]


def _priced(cost: float | None, price: float, basis: str) -> list[str]:
    """One cost line, attributed to the basis that produced the token count.

    Measured and estimated counts are never added together: a rate applied to
    a blend of the two produces a figure neither basis supports.
    """
    if cost is None:
        return []
    return [f"    at ${price:g}/M that is ${cost:.6f} of input, by {basis}"]


def render(data: dict) -> str:
    if not data.get("operations"):
        return "CONTEXT COMPACTION — no operations recorded; provider savings unknown"
    removed = data["input_bytes"] - data["output_bytes"]
    estimate = data["estimated"]
    price = estimate["price_per_million"]
    lines = ["CONTEXT COMPACTION — generated output, measured sizes",
             f"  {data['operations']:,} operations; {removed:,} bytes removed"]
    for tier, group in sorted(data.get("by_tier", {}).items()):
        lines.append(f"    {group['bytes_removed']:,} bytes over "
                     f"{group['operations']:,} {tier} operation(s)")
    if data.get("no_gain"):
        lines.append(f"  {data['no_gain']:,} of those removed nothing and were "
                     f"forwarded unchanged")
    lines.extend(_spent(data))
    lines.extend(_recalled(data.get("retrievals") or {}))
    if estimate["operations"]:
        lines.append(f"  ~{estimate['tokens_removed']:,} tokens removed across "
                     f"{estimate['operations']:,} operation(s), 4 chars/token estimate")
        lines.extend(_priced(estimate["potential_input_cost_reduction"], price,
                             "estimated"))
    for name, group in data["measured_tokens_by_tokenizer"].items():
        lines.append(f"  {group['tokens_removed']:,} tokens removed, measured by {name}")
        lines.extend(_priced(group["potential_input_cost_reduction"], price, name))
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
