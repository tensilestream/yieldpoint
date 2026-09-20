"""A reference agent built from LangGraph's own maintained parts.

The primary harness in ``langgraph_agent.py`` hand-writes the model adapter
and the tool-execution loop. That proves Yieldpoint's integration works, but
it leaves a question open: is the result a property of the checker, or an
artefact of a loop we wrote ourselves?

This answers that. Everything between the model and the tools is LangGraph's:
``ChatOllama`` binds the tools, ``ToolNode`` executes them, ``tools_condition``
decides when to stop. The only Yieldpoint parts are ``verify_node`` and
``make_router``, inserted after a write — which is exactly how a reader would
wire it into their own graph.

``create_react_agent`` is deliberately not used: LangGraph marks it deprecated
in favour of ``langchain.agents.create_agent``, and building a reference track
on a deprecated entry point would date it before it shipped.

This is a **reference track, not an A/B arm**. A different framework changes
tool serialisation, stopping behaviour and prompt accounting, so its numbers
are not comparable with the primary harness's — they answer "does the finding
reproduce", not "how much does the gate cost".

**What it found first.** Running it on qwen2.5-coder produced one turn and no
tool calls, because ``ChatOllama`` returns that model's tool calls as content
text rather than in ``tool_calls``::

    reply.tool_calls -> []
    reply.content    -> '{"name": "read_file", "arguments": {"path": "..."}}'

Raw Ollama does the same, which is why the primary harness carries
``tool_calls_of`` to read either spelling. That fallback was written to fix
what looked like our bug; this track shows the official stack has the same
gap, so the compensation is load-bearing rather than a patch over sloppiness.

The practical consequence for anyone wiring their own agent: a model can be
calling tools perfectly and still look like it is refusing, and the two need
opposite fixes. Check ``content`` before concluding a model cannot use tools.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_ollama import ChatOllama
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from typing_extensions import TypedDict

from langgraph_agent import SYSTEM
from yieldpoint.langgraph import BLOCK, ESCALATE, PASS, REPAIR, UNVERIFIED, make_router, repair_context, verify_node


class RefState(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    changes: list[dict[str, str | None]]
    turns: int
    wrote: bool
    called: list[str]
    verdict: dict[str, Any]
    prescription: str
    yieldpoint_history: list[str]
    yieldpoint_attempts: int
    yieldpoint_loop_tripped: bool


@dataclass
class RefSettings:
    model: str
    checkout: str
    test_command: str
    gated: bool
    max_turns: int = 10
    seed: int = 7
    temperature: float = 0.0
    changes: list[dict] = field(default_factory=list)
    called: list[str] = field(default_factory=list)
    pending_write: bool = False


def _resolver(root: Path):
    """Paths stay inside the checkout, and resolve to one spelling.

    Without this a model writing the same file by relative and absolute path
    records two changes where one happened.
    """
    def resolve(path: str) -> Path:
        target = (root / path).resolve()
        if target != root and root not in target.parents:
            raise ValueError(f"{path} is outside the checkout")
        return target
    return resolve


def _record(changes: list[dict], relative: str, before: str | None,
            content: str) -> None:
    existing = next((c for c in changes if c["path"] == relative), None)
    if existing:
        existing["after"] = content
    else:
        changes.append({"path": relative, "before": before, "after": content})


def build_tools(settings: RefSettings):
    """The same four tools, as LangChain tools so ToolNode can run them.

    Writes are recorded into ``settings.changes`` rather than returned in
    state: ToolNode owns the message plumbing, and reaching into it to thread
    a change set would reintroduce the custom loop this track exists to avoid.
    """
    root = Path(settings.checkout).resolve()
    resolve = _resolver(root)

    @tool
    def read_file(path: str) -> str:
        """Read a UTF-8 file from the checkout."""
        settings.called.append("read_file")
        return resolve(path).read_text(encoding="utf-8")[:4000]

    @tool
    def write_file(path: str, content: str) -> str:
        """Write a UTF-8 file into the checkout."""
        settings.called.append("write_file")
        target = resolve(path)
        relative = str(target.relative_to(root))
        before = target.read_text(encoding="utf-8") if target.exists() else None
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        _record(settings.changes, relative, before, content)
        settings.pending_write = True
        return f"wrote {relative}"

    @tool
    def list_files(glob: str = "*") -> str:
        """List checkout paths matching a glob."""
        settings.called.append("list_files")
        return "\n".join(str(p.relative_to(root))
                         for p in sorted(root.glob(glob))[:60])

    @tool
    def run_tests() -> str:
        """Run the task's test command."""
        settings.called.append("run_tests")
        done = subprocess.run(settings.test_command, shell=True, cwd=root,
                              capture_output=True, text=True, check=False)
        return (done.stdout + done.stderr)[-2000:]

    return [read_file, write_file, list_files, run_tests]


def lift_text_tool_calls(reply: AIMessage, names: frozenset[str]) -> AIMessage:
    """Move a tool call out of ``content`` and into ``tool_calls``.

    Only the *model adapter* is patched here. ToolNode still executes and
    tools_condition still decides when to stop, so the claim this track makes —
    that LangGraph's own stack drives the loop — is untouched.

    Needed because qwen2.5-coder declares the ``tools`` capability, and Ollama's
    template for it emits the call as JSON text anyway. ChatOllama reports no
    tool calls, which is indistinguishable from a model that refused.
    """
    if reply.tool_calls or not isinstance(reply.content, str):
        return reply
    found = _text_tool_calls(reply.content, names)
    if not found:
        return reply
    # Preserve IDs, token usage and provider metadata. The latter is the
    # evidence a reference run needs; rebuilding AIMessage loses it.
    return reply.model_copy(update={"content": "", "tool_calls": found})


def _text_tool_calls(content: str, names: frozenset[str]) -> list[dict]:
    """Decode complete JSON objects without mistaking braces in file content.

    A regex cannot balance the nested object passed to ``write_file``. Scan
    from each opening brace instead, and accept only a known tool with a dict
    argument object. Ordinary prose and unknown tool names remain messages.
    """
    decoder, found, offset = json.JSONDecoder(), [], 0
    while (start := content.find("{", offset)) >= 0:
        try:
            payload, end = decoder.raw_decode(content[start:])
        except json.JSONDecodeError:
            offset = start + 1
            continue
        offset = start + end
        name = payload.get("name") if isinstance(payload, dict) else None
        arguments = (payload.get("arguments", payload.get("parameters"))
                     if isinstance(payload, dict) else None)
        if name in names and isinstance(arguments, dict):
            found.append({"name": name, "args": arguments,
                          "id": f"call_{len(found)}", "type": "tool_call"})
    return found


def _agent_node(model, tools, settings: RefSettings):
    """The model turn. The only Yieldpoint part is the repair message."""
    names = frozenset(tool.name for tool in tools)

    def agent(state: RefState) -> dict:
        messages = list(state["messages"])
        if settings.gated and state.get("prescription"):
            messages.append(HumanMessage(content=repair_context(state)
                                         or state["prescription"]))
        reply = lift_text_tool_calls(model.invoke(messages), names)
        return {"messages": [reply], "turns": int(state.get("turns", 0)) + 1}

    return agent


def _collect_node(settings: RefSettings):
    """Hand ToolNode's writes to Yieldpoint in the shape it expects."""
    def collect(state: RefState) -> dict:
        return {"changes": [dict(c) for c in settings.changes],
                "called": list(settings.called),
                "wrote": bool(settings.changes)}

    return collect


def _add_gate(graph, settings: RefSettings) -> None:
    """Yieldpoint's shipped node and router, after a write. Nothing else."""
    graph.add_node("verify", verify_node(policy=".yieldpoint.json",
                                         root=settings.checkout))
    graph.add_conditional_edges(
        "collect", lambda state: "verify" if state.get("wrote") else "agent",
        {"verify": "verify", "agent": "agent"})
    graph.add_conditional_edges("verify", make_router(max_repairs=3),
                                {PASS: "agent", REPAIR: "agent",
                                 ESCALATE: END, UNVERIFIED: "agent"})


def build_graph(settings: RefSettings):
    """agent -> tools -> (verify) -> agent, with LangGraph owning the middle."""
    tools = build_tools(settings)
    model = ChatOllama(model=settings.model, temperature=settings.temperature,
                       seed=settings.seed).bind_tools(tools)

    graph = StateGraph(RefState)
    graph.add_node("agent", _agent_node(model, tools, settings))
    graph.add_node("tools", ToolNode(tools))
    graph.add_node("collect", _collect_node(settings))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition,
                                {"tools": "tools", END: END})
    graph.add_edge("tools", "collect")

    if settings.gated:
        _add_gate(graph, settings)
    else:
        graph.add_edge("collect", "agent")
    return graph.compile()


def run_reference(instruction: str, settings: RefSettings) -> dict:
    """One arm. Returns the same per-turn shape the primary harness writes."""
    graph = build_graph(settings)
    state = graph.invoke(
        {"messages": [SystemMessage(content=SYSTEM),
                      HumanMessage(content=instruction)]},
        {"recursion_limit": settings.max_turns * 4},
    )
    return {
        "turns": int(state.get("turns", 0)),
        "tools_called": list(settings.called),
        "files_changed": [c["path"] for c in settings.changes],
        "verdict": state.get("verdict", {}),
        "messages": sum(1 for m in state["messages"] if isinstance(m, AIMessage)),
    }


__all__ = ["RefSettings", "build_graph", "run_reference"]
