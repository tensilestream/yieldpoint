"""A tool-using Ollama agent whose optional gate is Yieldpoint's shipped graph."""

from __future__ import annotations

import json
import operator
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, TypedDict

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = (str(ROOT), str(ROOT / "benchmarks" / "ollama"))

from ollama_client import HOST, OllamaUnavailable  # noqa: E402
from yieldpoint.langgraph import (  # noqa: E402
    ESCALATE, PASS, REPAIR, UNVERIFIED, make_router, repair_context, verify_node,
)

SYSTEM = "You are a coding agent. Use the provided tools to fix the request. Run tests before finishing."
TOOLS = [{"type": "function", "function": {"name": name, "description": description,
          "parameters": {"type": "object", "properties": properties, "required": required}}}
         for name, description, properties, required in (
    ("read_file", "Read a UTF-8 file.", {"path": {"type": "string"}}, ["path"]),
    ("write_file", "Write a UTF-8 file.", {"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]),
    ("list_files", "List paths matching a glob.", {"glob": {"type": "string"}}, ["glob"]),
    ("run_tests", "Run the task's test command.", {}, []),
)]


class State(TypedDict, total=False):
    messages: Annotated[list[dict[str, Any]], operator.add]
    changes: list[dict[str, str | None]]
    next: str
    prompt_tokens: int
    output_tokens: int
    tool_calls: int
    turns: int
    seconds: float
    repair_seen: int
    history: Annotated[list[dict[str, Any]], operator.add]


@dataclass(frozen=True)
class ModelReply:
    message: dict[str, Any]
    prompt_tokens: int
    output_tokens: int
    seconds: float


@dataclass(frozen=True)
class AgentSettings:
    model: str
    checkout: str
    test_command: str
    gated: bool
    max_turns: int
    temperature: float = 0.0
    seed: int = 7


def _reply(model: str, messages: list[dict[str, Any]], temperature: float, seed: int) -> ModelReply:
    body = json.dumps({"model": model, "stream": False, "messages": messages,
                       "tools": TOOLS, "options": {"temperature": temperature, "seed": seed}}).encode()
    request = urllib.request.Request(f"{HOST}/api/chat", data=body,
                                     headers={"Content-Type": "application/json"})
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            payload = json.load(response)
    except (urllib.error.URLError, OSError) as exc:
        raise OllamaUnavailable(f"tool chat failed: {exc}") from exc
    return ModelReply(payload.get("message", {}), int(payload.get("prompt_eval_count") or 0),
                      int(payload.get("eval_count") or 0), time.perf_counter() - start)


class CheckoutTools:
    def __init__(self, checkout: str, test_command: str):
        self.root, self.test_command = Path(checkout).resolve(), test_command

    def call(self, name: str, arguments: dict[str, Any], changes: list[dict]) -> str:
        if name == "read_file":
            return self._read(str(arguments.get("path", "")))
        if name == "write_file":
            return self._write(str(arguments.get("path", "")), str(arguments.get("content", "")), changes)
        if name == "list_files":
            return "\n".join(str(p.relative_to(self.root)) for p in self.root.glob(str(arguments.get("glob", "**/*"))) if p.is_file())
        if name == "run_tests":
            import subprocess
            result = subprocess.run(self.test_command, shell=True, cwd=self.root, text=True,
                                    capture_output=True, check=False)
            return (result.stdout + result.stderr)[-12000:] + f"\nexit={result.returncode}"
        return f"Unknown tool: {name}"

    def _target(self, path: str) -> Path:
        target = (self.root / path).resolve()
        if self.root not in target.parents and target != self.root:
            raise ValueError("path escapes checkout")
        return target

    def _read(self, path: str) -> str:
        return self._target(path).read_text(encoding="utf-8")

    def _write(self, path: str, content: str, changes: list[dict]) -> str:
        target = self._target(path)
        before = target.read_text(encoding="utf-8") if target.exists() else None
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        previous = next((item for item in changes if item["path"] == path), None)
        if previous:
            previous["after"] = content
        else:
            changes.append({"path": path, "before": before, "after": content})
        return f"wrote {path}"

    def verdict(self) -> dict[str, Any]:
        import subprocess
        from yieldpoint.verify import verify_diff

        diff = subprocess.run(("git", "diff"), cwd=self.root, text=True,
                              capture_output=True, check=True).stdout
        verdict = verify_diff(diff, root=str(self.root))
        return {"status": verdict.status.value,
                "rules": sorted({item.rule for item in verdict.findings})}


class AgentRuntime:
    def __init__(self, settings: AgentSettings):
        self.settings = settings
        self.tools = CheckoutTools(settings.checkout, settings.test_command)

    def agent(self, state: State) -> dict:
        messages = list(state["messages"])
        attempts = int(state.get("yieldpoint_attempts", 0))
        if self.settings.gated and attempts > int(state.get("repair_seen", 0)):
            messages.append({"role": "user", "content": repair_context(state)})
        reply = _reply(self.settings.model, messages, self.settings.temperature,
                       self.settings.seed + int(state.get("turns", 0)) + 1)
        calls = reply.message.get("tool_calls") or []
        return {"messages": [reply.message], "next": "tools" if calls else "finish",
                "prompt_tokens": int(state.get("prompt_tokens", 0)) + reply.prompt_tokens,
                "output_tokens": int(state.get("output_tokens", 0)) + reply.output_tokens,
                "turns": int(state.get("turns", 0)) + 1, "tool_calls": int(state.get("tool_calls", 0)) + len(calls),
                "seconds": float(state.get("seconds", 0)) + reply.seconds, "repair_seen": attempts}

    def execute(self, state: State) -> dict:
        changes = [dict(item) for item in state.get("changes", [])]
        messages = []
        for call in state["messages"][-1].get("tool_calls") or []:
            function = call.get("function", {})
            try:
                content = self.tools.call(function.get("name", ""), function.get("arguments", {}), changes)
            except (OSError, ValueError) as exc:
                content = f"tool error: {exc}"
            messages.append({"role": "tool", "content": content})
        return {"messages": messages, "changes": changes}

    def observe(self, state: State) -> dict:
        report = self.tools.verdict()
        report["turn"] = int(state.get("turns", 0))
        report["prompt_tokens"] = int(state.get("prompt_tokens", 0))
        report["output_tokens"] = int(state.get("output_tokens", 0))
        return {"history": [report]}

    def after_observe(self, state: State) -> str:
        if state["next"] == "finish" or int(state.get("turns", 0)) >= self.settings.max_turns:
            return "verify" if self.settings.gated else "end"
        return "agent"


def build_graph(settings: AgentSettings):
    """Build the two arms; their only topological difference is ``verify``."""
    from langgraph.graph import END, START, StateGraph
    runtime = AgentRuntime(settings)

    graph = StateGraph(State)
    graph.add_node("agent", runtime.agent)
    graph.add_node("tools", runtime.execute)
    graph.add_node("observe", runtime.observe)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", lambda state: state["next"],
                                {"tools": "tools", "finish": "observe"})
    graph.add_edge("tools", "observe")
    graph.add_conditional_edges("observe", runtime.after_observe,
                                {"agent": "agent", "verify": "verify" if settings.gated else END, "end": END})
    if settings.gated:
        graph.add_node("verify", verify_node(policy=".yieldpoint.json", root=settings.checkout))
        graph.add_conditional_edges("verify", make_router(max_repairs=settings.max_turns),
                                    {PASS: END, REPAIR: "agent", ESCALATE: END, UNVERIFIED: END})
    return graph.compile()


def run_agent(instruction: str, settings: AgentSettings) -> dict:
    graph = build_graph(settings)
    state = graph.invoke({"messages": [{"role": "system", "content": SYSTEM},
                                        {"role": "user", "content": instruction}], "changes": []},
                         {"recursion_limit": settings.max_turns * 8})
    return dict(state)
