"""Minimal Ollama client over the stdlib, so this benchmark adds no dependency.

Talks to the local daemon at http://localhost:11434. Nothing here is imported
by the Yieldpoint core, which by policy never reaches the network
(RULES.md section 4) — this is benchmark scaffolding that lives outside it.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

HOST = "http://localhost:11434"
TIMEOUT_SECONDS = 600


class OllamaUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class Reply:
    text: str
    seconds: float
    prompt_tokens: int
    output_tokens: int
    thinking: str = ""
    """Hidden reasoning, when the model emits any.

    A reasoning model counts these tokens in ``eval_count`` but leaves them out
    of ``content``. Ignoring them undercounts what a turn actually cost, and
    makes a chars-per-token ratio look impossible (more tokens than characters).
    """

    @property
    def generated_chars(self) -> int:
        """Everything the model produced, visible or not."""
        return len(self.text) + len(self.thinking)


def installed_models() -> list[str]:
    """Every model tag `ollama list` would show."""
    try:
        with urllib.request.urlopen(f"{HOST}/api/tags", timeout=10) as response:
            payload = json.load(response)
    except (urllib.error.URLError, OSError) as exc:
        raise OllamaUnavailable(
            f"cannot reach the Ollama daemon at {HOST} ({exc}). "
            "Start it with `ollama serve`."
        ) from exc
    return sorted(m["name"] for m in payload.get("models", []))


def resolve_model(requested: str) -> str:
    """Accept a bare family name when exactly one installed tag matches it."""
    available = installed_models()
    if not available:
        raise OllamaUnavailable(
            "the Ollama daemon is running but has no models. "
            "Pull one first, e.g. `ollama pull gemma3:4b`."
        )
    if requested in available:
        return requested
    matches = [m for m in available if m.split(":")[0] == requested.split(":")[0]]
    if len(matches) == 1:
        return matches[0]
    raise OllamaUnavailable(
        f"model {requested!r} is not installed. Installed: {', '.join(available)}.\n"
        f"Pull it with `ollama pull {requested}`, or pass --model with one of the above."
    )


def converse(model: str, messages: list[dict], *, temperature: float, seed: int) -> Reply:
    """One turn of an ongoing conversation. Wall time is measured here, not
    reported by the daemon."""
    body = json.dumps({
        "model": model,
        "stream": False,
        "messages": messages,
        # Fixed seed and zero temperature so a re-run is as close to comparable
        # as a sampled model allows. It is not determinism; do not call it that.
        "options": {"temperature": temperature, "seed": seed},
    }).encode("utf-8")

    request = urllib.request.Request(
        f"{HOST}/api/chat", data=body,
        headers={"Content-Type": "application/json"},
    )
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            payload = json.load(response)
    except (urllib.error.URLError, OSError) as exc:
        raise OllamaUnavailable(f"request to {HOST}/api/chat failed: {exc}") from exc
    elapsed = time.perf_counter() - start

    message = payload.get("message", {})
    return Reply(
        text=message.get("content", ""),
        seconds=elapsed,
        prompt_tokens=int(payload.get("prompt_eval_count") or 0),
        output_tokens=int(payload.get("eval_count") or 0),
        thinking=message.get("thinking") or "",
    )


def chat(model: str, system: str, user: str, *, temperature: float, seed: int) -> Reply:
    """One non-streaming single-shot turn."""
    return converse(
        model,
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=temperature, seed=seed,
    )


_BLOCK = re.compile(
    r"===\s*FILE:\s*(?P<path>[^\s=]+)\s*===[ \t]*\n(?P<body>.*?)(?=\n===|\Z)",
    re.DOTALL,
)
_FENCE = re.compile(r"\A\s*```[a-zA-Z0-9_+-]*\s*\n(?P<body>.*?)\n?```\s*\Z", re.DOTALL)


def parse_files(text: str) -> dict[str, str]:
    """Pull `=== FILE: x.py ===` blocks out of a reply, tolerating code fences."""
    files: dict[str, str] = {}
    for match in _BLOCK.finditer(text):
        body = match.group("body")
        fenced = _FENCE.match(body)
        if fenced:
            body = fenced.group("body")
        files[match.group("path").strip()] = body.rstrip() + "\n"
    return files
