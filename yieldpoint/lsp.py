"""Diagnostics over the Language Server Protocol.

Deferred once in the plan on a weeks-of-work estimate, which was wrong. That
figure was for a *language server* — incremental parsing, completions, hover,
a document model. This is none of those. It is the diagnostics half alone:
a saved file, compared with its committed version, published as squiggles.

The comparison matters. A language server that reported "this file is 1,400
lines" every time you opened it would be the absolute-state checker the review
complained about, wearing a different hat. So the before-state comes from git,
which means an editor shows the same attribution the hook and CI do: what this
edit did, separately from what it walked into.

Speaks the protocol by hand over stdin and stdout. The core takes no
dependencies, and a JSON-RPC framing is forty lines.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

from .core.verdict import Confidence, Status

#: LSP severities. 1 error, 2 warning, 3 information, 4 hint.
ERROR, WARNING, INFORMATION = 1, 2, 3

_GATING = {Status.BLOCK, Status.ESCALATE}


def severity_for(finding, advisory: bool) -> int:
    """The same conservative mapping SARIF uses, for the same reason.

    A red squiggle is a claim the code is wrong. Only a finding this package
    can prove, and that the policy actually enforces, earns one.
    """
    if advisory or finding.confidence is not Confidence.EXACT:
        return INFORMATION
    return ERROR if finding.status in _GATING else WARNING


def path_of(uri: str) -> str:
    """The file a `file://` URI names, with percent-escapes undone."""
    normalized = uri.replace("\\", "/")
    parsed = urlparse(normalized)
    if parsed.netloc and len(parsed.netloc) == 2 and parsed.netloc[1] == ":":
        path = f"{parsed.netloc}{parsed.path}"
    else:
        path = parsed.path
    decoded = unquote(path)
    if len(decoded) >= 3 and decoded[0] == "/" and decoded[1].isalpha() and decoded[2] == ":":
        return decoded[1:]
    return decoded


def committed(path: str, root: Path) -> str | None:
    """The file as HEAD has it, or ``None`` when git cannot say.

    ``None`` becomes a new-file comparison, which is right for an untracked
    file and honest for a repository git cannot read.
    """
    try:
        relative = Path(path).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None
    try:
        done = subprocess.run(["git", "show", f"HEAD:{relative}"], cwd=str(root),
                              capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def diagnostics(verdict, policy) -> list[dict]:
    """One diagnostic per finding, anchored to the line it names."""
    from .sarif import advisory_rules

    advisory = advisory_rules(policy)
    out = []
    for finding in verdict.findings:
        line = max(0, finding.line - 1)
        out.append({
            "range": {"start": {"line": line, "character": 0},
                      "end": {"line": line, "character": 200}},
            "severity": severity_for(finding, finding.rule in advisory),
            "source": "yieldpoint",
            "code": finding.rule,
            "message": f"{finding.detail}\n{finding.prescription}",
        })
    return out


def analyse(uri: str, text: str | None, root: Path, policy) -> list[dict]:
    """Verify one document against its committed self."""
    from .verify import verify_change

    path = path_of(uri)
    after = text
    if after is None:
        try:
            after = Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return []
    try:
        relative = Path(path).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        relative = path
    verdict = verify_change(committed(path, root), after, relative, policy,
                            hand_edit=True)
    return diagnostics(verdict, policy)


def _read(stream) -> dict | None:
    """One framed JSON-RPC message, or ``None`` at end of input."""
    length = 0
    while True:
        line = stream.readline()
        if not line:
            return None
        line = line.strip()
        if not line:
            break
        if line.lower().startswith(b"content-length:"):
            length = int(line.split(b":", 1)[1])
    if not length:
        return None
    try:
        return json.loads(stream.read(length).decode("utf-8"))
    except (ValueError, UnicodeError):
        return None


def _write(stream, payload: dict) -> None:
    body = json.dumps(payload).encode("utf-8")
    stream.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
    stream.write(body)
    stream.flush()


CAPABILITIES = {
    "capabilities": {
        # Full text on every change: this verifies whole files, and an
        # incremental model would be a document store we do not need.
        "textDocumentSync": {"openClose": True, "save": {"includeText": True},
                             "change": 1},
    },
    "serverInfo": {"name": "yieldpoint"},
}


def serve(stdin=None, stdout=None, root: str | Path = ".", policy=None) -> int:
    """Read requests until the client goes away. Never raises at a client."""
    from .core.policy import Policy

    source = stdin or sys.stdin.buffer
    sink = stdout or sys.stdout.buffer
    base = Path(root)
    resolved = Policy.load(policy, root=root)

    while True:
        message = _read(source)
        if message is None:
            return 0
        method = message.get("method", "")
        if method == "initialize":
            _write(sink, {"jsonrpc": "2.0", "id": message.get("id"),
                          "result": CAPABILITIES})
        elif method == "shutdown":
            _write(sink, {"jsonrpc": "2.0", "id": message.get("id"), "result": None})
        elif method == "exit":
            return 0
        elif method in ("textDocument/didOpen", "textDocument/didSave",
                        "textDocument/didChange"):
            _publish(sink, message, base, resolved)


def _publish(sink, message: dict, root: Path, policy) -> None:
    """Send diagnostics for one document. A failure here must not end the session."""
    document = (message.get("params") or {}).get("textDocument") or {}
    uri = document.get("uri", "")
    if not uri:
        return
    text = (message.get("params") or {}).get("text") or document.get("text")
    try:
        found = analyse(uri, text, root, policy)
    except Exception as exc:  # an editor must never be taken down by a checker
        found = []
        print(f"yieldpoint lsp: {exc}", file=sys.stderr)
    _write(sink, {"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics",
                  "params": {"uri": uri, "diagnostics": found}})


def lsp_command(args) -> int:
    return serve(root=args.root, policy=args.policy)


def add_command(sub) -> None:
    command = sub.add_parser(
        "lsp", help="serve diagnostics over the Language Server Protocol, on stdio")
    command.add_argument("--root", default=".")
    command.add_argument("--policy", default=None)
    command.set_defaults(handler=lsp_command)


__all__ = ["serve", "analyse", "diagnostics", "severity_for", "path_of",
           "lsp_command", "add_command"]
