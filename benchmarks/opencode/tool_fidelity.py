"""How many tools can a local model be offered before it stops calling them?

Off-the-shelf coding agents (opencode, OpenHands, Claude Code) hand the model
a large tool surface. A model that emits a structured ``tool_calls`` reply when
offered one tool may emit a *markdown code block imitating* a tool call when
offered ten -- which no agent runtime can execute. The agent then finishes
having changed nothing, and reports success.

This measures where that happens, per model, with no agent in the loop. The
same task and the same request every time; three things vary, one at a time:

  --repeats       how many tools are offered, 1 through 10
  --endpoint      native /api/chat, or OpenAI-compatible /v1/chat/completions
  --system-file   a short prompt, or a real agent's full system prompt

Isolating them matters. A model that answers in prose inside opencode may be
perfect on all ten tools when asked directly -- in which case the tool surface
is exonerated and the system prompt is the cause, which is a configuration
problem rather than a model limit.

    python benchmarks/opencode/tool_fidelity.py --model llama3.1:latest
    python benchmarks/opencode/tool_fidelity.py --model llama3.1:latest \
        --endpoint openai --system-file captured/opencode_system.txt \
        --label opencode-prompt

Zero dependencies. Reads OLLAMA_HOST, default http://localhost:11434.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, replace

HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
TIMEOUT = 300

#: Ordered as opencode presents them. The first is always the one the task
#: needs, so a failure is never "the right tool was not offered".
TOOLS = [
    ("write", "Write the complete contents of a file, replacing it.",
     {"filePath": "Path to the file", "content": "Full new file contents"}),
    ("read", "Read the contents of a file.",
     {"filePath": "Path to the file"}),
    ("bash", "Run a shell command and return its output.",
     {"command": "The command to run"}),
    ("edit", "Replace an exact string in a file with another.",
     {"filePath": "Path to the file", "oldString": "Text to replace",
      "newString": "Replacement text"}),
    ("glob", "Find files matching a glob pattern.",
     {"pattern": "The glob pattern"}),
    ("grep", "Search file contents with a regular expression.",
     {"pattern": "The regular expression"}),
    ("todowrite", "Record a structured task list for the session.",
     {"todos": "The task list"}),
    ("webfetch", "Fetch a URL and return its contents as text.",
     {"url": "The URL to fetch"}),
    ("task", "Delegate a subtask to a general-purpose subagent.",
     {"prompt": "The subtask", "description": "Short label"}),
    ("skill", "Invoke a named skill with a prompt.",
     {"name": "Skill name", "prompt": "The prompt"}),
]

SYSTEM = (
    "You are a coding agent. You act only by calling tools. "
    "Never answer in prose and never write code in your reply."
)

#: The same repair, asked two ways. The difference is the whole point: one
#: names the tool and hands over the file, the other states a goal and leaves
#: the model to decide that a tool is needed at all. A model can be flawless
#: at the first and useless at the second, and only the second is what an
#: agent actually asks of it.
TASKS = {
    "directed": (
        "The file calc.py contains:\n\n"
        "def total(subtotal, vat_rate):\n"
        '    """Subtotal plus VAT."""\n'
        "    return subtotal\n\n"
        "The test asserts total(100, 0.2) == 120. "
        "Use the write tool to replace calc.py with a correct implementation."
    ),
    "agentic": "Edit calc.py so test_calc.py passes.",
}

USER = TASKS["directed"]


def schema(name: str, description: str, params: dict[str, str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {k: {"type": "string", "description": v}
                               for k, v in params.items()},
                "required": list(params),
            },
        },
    }


class OllamaUnavailable(RuntimeError):
    """The daemon could not be reached. Distinct from a bad answer."""


#: Both endpoints Ollama exposes. An agent picks one; the answer can differ,
#: so the endpoint is a variable this sweep controls rather than assumes.
ENDPOINTS = {
    "native": "/api/chat",
    "openai": "/v1/chat/completions",
}


@dataclass(frozen=True)
class Probe:
    """How one question is put to the model.

    These four travel together -- change any of them and you are measuring a
    different configuration, so they are one value rather than four arguments
    threaded through every call.
    """

    system: str = SYSTEM
    user: str = USER
    endpoint: str = "native"
    temperature: float = 0.0
    seed: int = 7

    def at(self, run: int) -> Probe:
        """The same probe on its Nth repeat. Only the seed moves."""
        return replace(self, seed=self.seed + run)

    def sampling(self) -> dict:
        """Temperature and seed, spelled the way this endpoint expects."""
        knobs = {"temperature": self.temperature, "seed": self.seed}
        return {"options": knobs} if self.endpoint == "native" else knobs


def _body(model: str, tools: list[dict], probe: Probe) -> dict:
    return {
        "model": model,
        "messages": [{"role": "system", "content": probe.system},
                     {"role": "user", "content": probe.user}],
        "tools": tools,
        "stream": False,
        **probe.sampling(),
    }


def ask(model: str, tools: list[dict], probe: Probe) -> dict:
    request = urllib.request.Request(
        HOST + ENDPOINTS[probe.endpoint],
        data=json.dumps(_body(model, tools, probe)).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read())
    except urllib.error.URLError as exc:
        raise OllamaUnavailable(f"{HOST} unreachable: {exc}") from exc


def _message(reply: dict) -> dict:
    """The assistant turn, under whichever key the endpoint used."""
    if "message" in reply:
        return reply["message"]
    choices = reply.get("choices") or [{}]
    return choices[0].get("message", {})


def classify(reply: dict) -> str:
    """What the runtime would actually be able to execute."""
    message = _message(reply)
    calls = message.get("tool_calls") or []
    if calls:
        names = [c.get("function", {}).get("name") for c in calls]
        return "structured:" + ",".join(n for n in names if n)
    text = (message.get("content") or "").strip()
    if not text:
        return "empty"
    if any(marker in text for marker in ('"name"', "```", "tool_call", "<function")):
        return "text-imitation"
    return "prose"


def sweep(model: str, probe: Probe, *, repeats: int) -> list[dict]:
    results = []
    for count in range(1, len(TOOLS) + 1):
        offered = [schema(*t) for t in TOOLS[:count]]
        verdicts = []
        for run in range(repeats):
            verdicts.append(classify(ask(model, offered, probe.at(run))))
        structured = sum(1 for v in verdicts if v.startswith("structured:"))
        results.append({
            "tools_offered": count,
            "structured": structured,
            "repeats": repeats,
            "verdicts": verdicts,
        })
        print(f"  {count:2d} tools -> {structured}/{repeats} structured "
              f"({verdicts[0]})", flush=True)
    return results


def render(model: str, results: list[dict], *, note: str = "") -> str:
    lines = [f"# tool-calling fidelity: {model}", ""]
    if note:
        lines += [note, ""]
    lines += [
             "| tools offered | structured tool calls | first verdict |",
             "|---|---|---|"]
    for row in results:
        lines.append(f"| {row['tools_offered']} | "
                     f"{row['structured']}/{row['repeats']} | "
                     f"`{row['verdicts'][0]}` |")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="llama3.1:latest")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--repeats", type=int, default=3,
                        help="runs per tool count; a single run proves nothing")
    parser.add_argument("--system-file", default="",
                        help="replay a real agent's system prompt instead of "
                             "this script's short one")
    parser.add_argument("--endpoint", choices=sorted(ENDPOINTS), default="native",
                        help="which Ollama API to ask through (default: %(default)s)")
    parser.add_argument("--task", choices=sorted(TASKS), default="directed",
                        help="'directed' names the tool and supplies the file; "
                             "'agentic' states only the goal (default: %(default)s)")
    parser.add_argument("--label", default="",
                        help="suffix for the results filename")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    system = SYSTEM
    if args.system_file:
        with open(args.system_file, encoding="utf-8") as fh:
            system = fh.read()
    print(f"model: {args.model}   repeats: {args.repeats}   "
          f"endpoint: {args.endpoint}   task: {args.task}   "
          f"system: {len(system)} chars\n")
    probe = Probe(system=system, user=TASKS[args.task],
                  endpoint=args.endpoint, temperature=args.temperature,
                  seed=args.seed)
    try:
        results = sweep(args.model, probe, repeats=args.repeats)
    except OllamaUnavailable as exc:
        print(f"\nerror: {exc}", file=sys.stderr)
        return 2

    table = render(args.model, results,
                   note=f"endpoint `{args.endpoint}`, task `{args.task}`, "
                        f"system prompt {len(system)} chars")
    print("\n" + table)

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    os.makedirs(out, exist_ok=True)
    stem = args.model.replace(":", "-").replace("/", "-")
    if args.label:
        stem = f"{stem}-{args.label}"
    with open(os.path.join(out, f"fidelity-{stem}.md"), "w") as fh:
        fh.write(table)
    with open(os.path.join(out, f"fidelity-{stem}.json"), "w") as fh:
        json.dump({"model": args.model, "results": results}, fh, indent=2)
    print(f"wrote {out}/fidelity-{stem}.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
