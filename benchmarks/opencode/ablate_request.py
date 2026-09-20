"""Find which part of a real agent's request stops a local model calling tools.

Takes a request body captured off the wire between an agent and Ollama, and
replays it with one thing changed at a time. Everything else is byte-identical,
so a variant that flips the outcome names the cause rather than suggesting one.

    python benchmarks/opencode/ablate_request.py \
        --body benchmarks/opencode/captured/opencode_request.json

The captured opencode body scores 0/4: the model answers with prose that looks
like a tool call. Truncating each tool description to its first line scores
4/4. Nothing else in the request matters -- not the 11,823-character system
prompt, not the ten tools, not the JSON Schema draft key, not temperature.

Zero dependencies. Reads OLLAMA_HOST, default http://localhost:11434.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import urllib.error
import urllib.request

HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
PATH = "/v1/chat/completions"
TIMEOUT = 300


class OllamaUnavailable(RuntimeError):
    """The daemon could not be reached. Distinct from a bad answer."""


def unstreamed(body: dict) -> dict:
    """A single JSON reply, so a variant is read the same way every time."""
    payload = copy.deepcopy(body)
    payload["stream"] = False
    payload.pop("stream_options", None)
    payload["temperature"] = 0
    return payload


def drop_schema_key(body: dict) -> dict:
    payload = copy.deepcopy(body)
    for tool in payload.get("tools") or []:
        tool.get("function", {}).get("parameters", {}).pop("$schema", None)
    return payload


def first_line_descriptions(body: dict) -> dict:
    payload = copy.deepcopy(body)
    for tool in payload.get("tools") or []:
        function = tool.get("function", {})
        text = function.get("description")
        if text:
            function["description"] = text.splitlines()[0]
    return payload


def no_system_prompt(body: dict) -> dict:
    payload = copy.deepcopy(body)
    payload["messages"] = [m for m in payload["messages"] if m["role"] != "system"]
    return payload


VARIANTS = (
    ("baseline (unchanged)", lambda b: b),
    ("no $schema in parameters", drop_schema_key),
    ("tool descriptions, first line only", first_line_descriptions),
    ("no system prompt", no_system_prompt),
    ("first line + no system prompt",
     lambda b: first_line_descriptions(no_system_prompt(b))),
)


def ask(body: dict) -> list[str]:
    """The tool names the runtime could actually execute. Empty means none."""
    request = urllib.request.Request(
        HOST + PATH, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            message = json.loads(response.read())["choices"][0]["message"]
    except urllib.error.URLError as exc:
        raise OllamaUnavailable(f"{HOST} unreachable: {exc}") from exc
    return [c["function"]["name"] for c in (message.get("tool_calls") or [])]


def run(body: dict, repeats: int) -> list[dict]:
    results = []
    for label, transform in VARIANTS:
        calls = [ask(transform(body)) for _ in range(repeats)]
        hits = sum(1 for c in calls if c)
        results.append({"variant": label, "structured": hits,
                        "repeats": repeats, "first": calls[0]})
        print(f"  {label:36} {hits}/{repeats}   "
              f"{','.join(calls[0]) or 'text, not a tool call'}", flush=True)
    return results


def render(results: list[dict], source: str) -> str:
    lines = [f"# which part of the request breaks tool calling", "",
             f"replayed from `{source}`, one change at a time", "",
             "| variant | structured tool calls | first reply |", "|---|---|---|"]
    for row in results:
        called = ",".join(row["first"]) or "text, not a tool call"
        lines.append(f"| {row['variant']} | {row['structured']}/{row['repeats']} "
                     f"| `{called}` |")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--body", required=True,
                        help="captured chat-completions request body, JSON")
    parser.add_argument("--repeats", type=int, default=4)
    parser.add_argument("--label", default="opencode")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    with open(args.body, encoding="utf-8") as fh:
        body = unstreamed(json.load(fh))

    tools = len(body.get("tools") or [])
    print(f"model: {body.get('model')}   tools: {tools}   "
          f"repeats: {args.repeats}\n")
    try:
        results = run(body, args.repeats)
    except OllamaUnavailable as exc:
        print(f"\nerror: {exc}", file=sys.stderr)
        return 2

    table = render(results, os.path.basename(args.body))
    print("\n" + table)

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, f"ablation-{args.label}.md"), "w") as fh:
        fh.write(table)
    print(f"wrote {out}/ablation-{args.label}.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
