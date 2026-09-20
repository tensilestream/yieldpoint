"""Sit between a coding agent and Ollama, and thin the tool descriptions.

Measured with benchmarks/opencode/ablate_request.py: llama3.1 offered
opencode's ten tools verbatim emits a *textual imitation* of a tool call 0/4
times correctly. Truncate each tool description to its first line -- nothing
else -- and the same model, same prompt, same tools answers with a real
structured call 4/4 times.

opencode's descriptions are prose paragraphs of MUST and NEVER. A frontier
model reads them as guidance. A 7-8B model reads them as the thing to imitate,
and writes about calling a tool instead of calling one. The agent then finishes
having edited nothing, and exits 0.

Point the agent's baseURL at this proxy:

    python benchmarks/opencode/leanproxy.py --port 11555
    # opencode.json: "baseURL": "http://127.0.0.1:11555/v1"

Zero dependencies. Forwards everything else untouched, streaming included.
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FORWARD_HEADERS = ("content-type", "cache-control")


def thin(description: str, *, lines: int) -> str:
    """The first ``lines`` lines of a description, blank lines dropped."""
    kept = [line for line in description.splitlines() if line.strip()][:lines]
    return "\n".join(kept)


def rewrite(payload: dict, *, lines: int) -> tuple[dict, int]:
    """Shorten every tool description in a chat-completions body."""
    tools = payload.get("tools") or []
    touched = 0
    for tool in tools:
        function = tool.get("function") or {}
        original = function.get("description")
        if not original:
            continue
        shortened = thin(original, lines=lines)
        if shortened != original:
            function["description"] = shortened
            touched += 1
    return payload, touched


class Handler(BaseHTTPRequestHandler):
    upstream = "http://localhost:11434"
    lines = 1
    verbose = True

    def log_message(self, *args) -> None:
        """Silence the default per-request logging; we print our own."""

    def _announce(self, touched: int, payload: dict) -> None:
        if not self.verbose:
            return
        tools = len(payload.get("tools") or [])
        print(f"  {self.path}  tools={tools}  thinned={touched}", flush=True)

    def _body(self) -> bytes:
        return self.rfile.read(int(self.headers.get("Content-Length", 0)))

    def do_POST(self) -> None:
        raw = self._body()
        try:
            payload, touched = rewrite(json.loads(raw), lines=self.lines)
            raw = json.dumps(payload).encode()
            self._announce(touched, payload)
        except (ValueError, AttributeError):
            pass  # not JSON we understand; forward it exactly as received
        self._relay("POST", raw)

    def do_GET(self) -> None:
        self._relay("GET", None)

    def _relay(self, method: str, data: bytes | None) -> None:
        request = urllib.request.Request(
            self.upstream + self.path, data=data, method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=600) as response:
                self._begin(response)
                self._pump(response)
        except urllib.error.URLError as exc:
            self.send_error(502, f"upstream {self.upstream}: {exc}")

    def _begin(self, response) -> None:
        self.send_response(response.status)
        for key, value in response.getheaders():
            if key.lower() in FORWARD_HEADERS:
                self.send_header(key, value)
        self.end_headers()

    def _pump(self, response) -> None:
        """Stream the reply through as it arrives, so SSE stays live."""
        while True:
            chunk = response.read(8192)
            if not chunk:
                return
            try:
                self.wfile.write(chunk)
                self.wfile.flush()
            except BrokenPipeError:
                return


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=11555)
    parser.add_argument("--upstream", default="http://localhost:11434")
    parser.add_argument("--lines", type=int, default=1,
                        help="lines of each tool description to keep")
    parser.add_argument("--quiet", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    Handler.upstream = args.upstream.rstrip("/")
    Handler.lines = args.lines
    Handler.verbose = not args.quiet
    print(f"lean proxy on http://127.0.0.1:{args.port} -> {Handler.upstream}")
    print(f"keeping {args.lines} line(s) of each tool description\n")
    try:
        ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
