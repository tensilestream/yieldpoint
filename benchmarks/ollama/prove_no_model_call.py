"""Prove, on this machine, that the verification path makes no model call.

    python benchmarks/ollama/prove_no_model_call.py

The claim under test is narrow and worth stating exactly: *the verification
path* — `verify_change` and `verify_diff` — reaches no network and spawns no
process. The benchmark harness next to this file very much does call Ollama;
that is the point of it, and check 5 uses it as a negative control.

A test that cannot fail proves nothing, so the network blocker here counts
attempts rather than catching errors: a blocked call that never happened and a
blocked call that was refused look identical from the outside otherwise.
"""

from __future__ import annotations

import hashlib
import json
import socket
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

NETWORK_MODULES = (
    "socket", "urllib", "http", "requests", "httpx", "aiohttp",
    "openai", "anthropic", "ollama", "grpc", "websockets",
)

BEFORE = "def test_total():\n    assert total() == 42\n"
AFTER = "def test_total():\n    assert total() is not None\n"
DIFF = (
    "--- a/tests/test_x.py\n+++ b/tests/test_x.py\n@@ -1,2 +1,2 @@\n"
    " def test_total():\n-    assert total() == 42\n+    assert total() is not None\n"
)
POLICY = {"test_contract": {"protected_patterns": ["**/test_*.py"]}}


class Tripwire(RuntimeError):
    """Raised the moment anything under test reaches for the outside world."""


@contextmanager
def sealed():
    """Cut every route off the machine, and record each attempt to take one."""
    attempts: list[str] = []
    saved = {
        "socket": socket.socket,
        "create_connection": socket.create_connection,
        "getaddrinfo": socket.getaddrinfo,
        "run": subprocess.run,
        "Popen": subprocess.Popen,
        "check_output": subprocess.check_output,
    }

    def trip(name):
        def blocked(*args, **kwargs):
            attempts.append(f"{name}{args[:1]}")
            raise Tripwire(f"blocked: {name}")
        return blocked

    for name in saved:
        target = socket if hasattr(socket, name) else subprocess
        setattr(target, name, trip(name))
    try:
        yield attempts
    finally:
        for name, original in saved.items():
            target = socket if hasattr(socket, name) else subprocess
            setattr(target, name, original)


def workload() -> str:
    """One real verdict of each kind, fingerprinted."""
    from yieldpoint.verify import verify_change, verify_diff

    change = verify_change(BEFORE, AFTER, "tests/test_x.py", POLICY)
    diffed = verify_diff(DIFF, ROOT, POLICY, read=lambda rel: AFTER)
    blob = change.to_json(indent=2) + diffed.to_json(indent=2)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def check_declared_dependencies() -> tuple[bool, str]:
    """A package with no dependencies cannot smuggle an SDK in behind one."""
    import tomllib

    raw = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = raw["project"]["dependencies"]
    return not declared, f"runtime dependencies declared: {declared or 'none'}"


def check_static_imports() -> tuple[bool, str]:
    """No module in the core names a network library at all."""
    import re

    pattern = re.compile(
        r"^\s*(?:import|from)\s+(" + "|".join(NETWORK_MODULES) + r")\b", re.M)
    guilty = [
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "yieldpoint" / "core").rglob("*.py")
        if pattern.search(path.read_text(encoding="utf-8"))
    ]
    return not guilty, f"core modules importing a network library: {guilty or 'none'}"


def check_loaded_modules() -> tuple[bool, str]:
    """Import the verification path in a clean process; see what it dragged in."""
    probe = (
        "import sys, json\n"
        "from yieldpoint.verify import verify_change, verify_diff\n"
        f"names = {NETWORK_MODULES!r}\n"
        "hit = sorted(m for m in sys.modules if m.split('.')[0] in names)\n"
        "print(json.dumps(hit))\n"
    )
    finished = subprocess.run(
        [sys.executable, "-c", probe], cwd=ROOT,
        capture_output=True, text=True, timeout=60,
    )
    loaded = json.loads(finished.stdout or "[]")
    # `socket` arrives via the stdlib's own import machinery on some builds;
    # what matters is that no client library did.
    clients = [m for m in loaded if m.split(".")[0] != "socket"]
    return not clients, f"network client modules loaded on import: {clients or 'none'}"


def check_sealed_verification() -> tuple[bool, str]:
    """The load-bearing check: run real verdicts with every exit sealed."""
    with sealed() as attempts:
        digest = workload()
    return not attempts, (
        f"verdicts produced with network and subprocess sealed (fingerprint {digest}); "
        f"attempts to escape: {attempts or 'none'}"
    )


def check_negative_control() -> tuple[bool, str]:
    """Does the seal actually have teeth? Point it at something that DOES call out."""
    from ollama_client import installed_models

    with sealed() as attempts:
        try:
            installed_models()
        except Exception:
            pass
    return bool(attempts), (
        f"seal caught the Ollama client reaching out: {attempts or 'NOTHING — seal is inert'}"
    )


def check_determinism_in_process(runs: int = 500) -> tuple[bool, str]:
    """A sampled model cannot do this. Same input, same bytes, every time."""
    digests = {workload() for _ in range(runs)}
    return len(digests) == 1, (
        f"{runs} runs produced {len(digests)} distinct verdict fingerprint(s): "
        f"{sorted(digests)}"
    )


def check_determinism_across_processes() -> tuple[bool, str]:
    """Different hash seeds, fresh interpreters — still byte-identical."""
    probe = (
        "import sys, hashlib\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        f"sys.path.insert(0, {str(Path(__file__).resolve().parent)!r})\n"
        "from prove_no_model_call import workload\n"
        "print(workload())\n"
    )
    digests = set()
    for seed in ("0", "1", "42", "random"):
        finished = subprocess.run(
            [sys.executable, "-c", probe], cwd=ROOT, capture_output=True,
            text=True, timeout=60, env={**__import__("os").environ,
                                        "PYTHONHASHSEED": seed},
        )
        digests.add(finished.stdout.strip() or f"FAILED: {finished.stderr[-200:]}")
    return len(digests) == 1, (
        f"4 interpreters with different PYTHONHASHSEED produced "
        f"{len(digests)} fingerprint(s): {sorted(digests)}"
    )


def check_latency_is_physically_impossible() -> tuple[bool, str]:
    """Supporting evidence: a round trip cannot fit in the time a verdict takes."""
    import statistics
    import time

    from yieldpoint.verify import verify_change

    verify_change(BEFORE, AFTER, "tests/test_x.py", POLICY)  # warm the parse cache
    samples = []
    for _ in range(50):
        start = time.perf_counter()
        verify_change(BEFORE, AFTER, "tests/test_x.py", POLICY)
        samples.append((time.perf_counter() - start) * 1000)
    median = statistics.median(samples)
    return median < 5.0, (
        f"median verdict {median:.3f} ms — a localhost round trip to a model "
        f"is orders of magnitude slower than this"
    )


CHECKS = (
    ("declared dependencies", check_declared_dependencies),
    ("static imports in core", check_static_imports),
    ("modules loaded on import", check_loaded_modules),
    ("verdicts under a sealed network", check_sealed_verification),
    ("negative control: seal has teeth", check_negative_control),
    ("determinism, 500 runs in-process", check_determinism_in_process),
    ("determinism, across interpreters", check_determinism_across_processes),
    ("verdict latency", check_latency_is_physically_impossible),
)


def main() -> int:
    print("Proving: the verification path makes no model call.\n")
    failures = 0
    for index, (title, check) in enumerate(CHECKS, start=1):
        try:
            ok, detail = check()
        except Exception as exc:  # a check that errors is a check that failed
            ok, detail = False, f"check raised {type(exc).__name__}: {exc}"
        failures += not ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {index}. {title}\n         {detail}\n")

    print("-" * 72)
    if failures:
        print(f"{failures} of {len(CHECKS)} checks FAILED. The claim does not hold here.")
    else:
        print(f"All {len(CHECKS)} checks passed on this machine.")
        print("Note the scope: this covers verify_change and verify_diff. The")
        print("benchmark harness beside it calls Ollama deliberately — check 5 is")
        print("the proof that this harness would have noticed if the core did too.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
