"""MCP stdio transport.

Newline-delimited JSON-RPC 2.0 on stdin and stdout, which is what the Model
Context Protocol's stdio transport is — so no dependency is needed to speak it.

Two rules shape the implementation:

**stdout carries protocol, nothing else.** A stray print corrupts the stream and
the client disconnects, so diagnostics go to stderr and every handler is wrapped.

**A malformed request must not end the session.** An unparseable line, an unknown
method or a failing tool each produce an error response and the loop continues.
An editor integration that dies on one bad message is worse than none.
"""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO

from .. import __version__
from ..core.policy import Policy
from .tools import TOOLS, call

#: Revision implemented here. The client's requested revision is echoed back when
#: it looks like a valid date-stamped version, which is how MCP negotiates.
PROTOCOL_VERSION = "2024-11-05"

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INTERNAL_ERROR = -32603


def serve(
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    policy: Policy | str | dict | None = None,
) -> int:
    """Run the server until stdin closes."""
    source = stdin or sys.stdin
    sink = stdout or sys.stdout
    resolved = Policy.load(policy)

    for line in source:
        line = line.strip()
        if not line:
            continue
        response = handle(line, resolved)
        if response is None:
            continue  # a notification takes no reply
        sink.write(json.dumps(response) + "\n")
        sink.flush()
    return 0


def handle(line: str, policy: Policy) -> dict[str, Any] | None:
    """Turn one request line into one response, or None for a notification."""
    try:
        message = json.loads(line)
    except json.JSONDecodeError:
        return _error(None, PARSE_ERROR, "invalid JSON")
    if not isinstance(message, dict):
        return _error(None, INVALID_REQUEST, "request must be an object")

    identifier = message.get("id")
    method = message.get("method")
    params = message.get("params") or {}

    if method is None:
        return _error(identifier, INVALID_REQUEST, "missing method")
    if identifier is None:
        return None  # notification: acknowledged by doing nothing

    try:
        return _dispatch(method, params, identifier, policy)
    except Exception as exc:  # never let one request end the session
        return _error(identifier, INTERNAL_ERROR, f"{method} failed: {exc}")


def _dispatch(method: str, params: dict, identifier: Any, policy: Policy):
    if method == "initialize":
        return _result(identifier, _initialize(params))
    if method == "ping":
        return _result(identifier, {})
    if method == "tools/list":
        return _result(identifier, {"tools": TOOLS})
    if method == "tools/call":
        return _result(identifier, _call(params, policy))
    if method in ("resources/list", "prompts/list"):
        key = method.split("/")[0]
        return _result(identifier, {key: []})
    return _error(identifier, METHOD_NOT_FOUND, f"unknown method: {method}")


def _initialize(params: dict) -> dict:
    requested = params.get("protocolVersion")
    version = requested if _is_version(requested) else PROTOCOL_VERSION
    return {
        "protocolVersion": version,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": "aegisflow", "version": __version__},
        "instructions": (
            "AegisFlow checks, deterministically and without any model call, whether a "
            "change weakens what the test suite verifies.\n"
            "\n"
            "Call aegis_review after finishing a set of edits and before reporting the "
            "work as done. It takes no arguments, reads the diff from git, and is the "
            "cheapest way to find out whether anything was weakened.\n"
            "\n"
            "Call aegis_verify_change before editing a protected test file, to check a "
            "specific edit ahead of writing it.\n"
            "\n"
            "Call aegis_policy before planning work, to see which rules and limits are "
            "in force in this repository.\n"
            "\n"
            "Every verdict carries a prescription naming exactly what to restore, so a "
            "rejected change does not need to be diagnosed by guessing. A verdict of "
            "'unverified' means no rule could analyse the change — it is not a pass."
        ),
    }


def _call(params: dict, policy: Policy) -> dict:
    name = params.get("name", "")
    arguments = params.get("arguments") or {}
    text, structured, is_error = call(name, arguments, policy)
    result: dict[str, Any] = {
        "content": [{"type": "text", "text": text}],
        "isError": is_error,
    }
    if structured:
        result["structuredContent"] = structured
    return result


def _is_version(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 10 and value.count("-") == 2


def _result(identifier: Any, payload: dict) -> dict:
    return {"jsonrpc": "2.0", "id": identifier, "result": payload}


def _error(identifier: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": identifier, "error": {"code": code, "message": message}}
