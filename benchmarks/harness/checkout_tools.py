"""The sandbox an agent's tools run in, and the normalisation they need.

Split from the agent graph because the two change for different reasons: that
one when the conversation shape changes, this one when a tool's output turns
out to carry something that varies between runs. Both of those have happened.

Everything here exists to make two runs of the same seed produce the same
bytes. A tool result the model reads is part of its context, so anything in it
that differs between runs — a temp directory name, a duration — makes the two
arms of an A/B diverge from that point on, and the comparison then measures the
divergence instead of the change.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


#: How long a suite took, as unittest and pytest both report it. The number is
#: a measurement of the machine, never of the change under test, so it carries
#: no information a model should be reading.
DURATION = re.compile(r"\bin \d+\.\d+s")


class CheckoutTools:
    def __init__(self, checkout: str, test_command: str):
        self.root, self.test_command = Path(checkout).resolve(), test_command

    @property
    def _spellings(self) -> tuple[str, ...]:
        """Every way this checkout's path can be written.

        macOS resolves /var to /private/var, so a tool that prints an
        unresolved path would slip past a single replacement. Longest first,
        or the shorter form leaves a fragment of the longer one behind.
        """
        root = str(self.root)
        candidates = {root, str(Path(self.root).absolute())}
        if root.startswith("/private/"):
            candidates.add(root[len("/private"):])
        return tuple(sorted(candidates, key=len, reverse=True))

    def _stable(self, text: str) -> str:
        """Remove everything in a tool result that varies between runs.

        Each arm runs in a fresh temp directory whose name is random, and that
        name appears in pytest output, tracebacks and import errors. It reaches
        the model through tool results, so the context differs between runs and
        two runs of the same seed diverge from the first failure onward. The
        benchmark was not reproducible, and a benchmark that is not
        reproducible cannot support a claim.

        Durations go too. Both unittest ("Ran 1 test in 0.056s") and pytest
        ("1 failed in 0.12s") print how long the suite took, and that figure
        is different on every run of the same code — measured at 0.055s and
        0.056s across five runs of one unchanged suite. It reaches the model
        exactly as the path did.
        """
        for spelling in self._spellings:
            text = text.replace(spelling, "/workspace")
        return DURATION.sub("in 0.000s", text)

    def call(self, name: str, arguments: dict[str, Any], changes: list[dict]) -> str:
        return self._stable(self._dispatch(name, arguments, changes))

    def _dispatch(self, name: str, arguments: dict[str, Any],
                  changes: list[dict]) -> str:
        if name == "read_file":
            return self._read(str(arguments.get("path", "")))
        if name == "write_file":
            return self._write(str(arguments.get("path", "")), str(arguments.get("content", "")), changes)
        if name == "list_files":
            # Sorted because Path.glob guarantees no order. It happens to be
            # stable on APFS, which is how this passed unnoticed: the listing
            # reaches the model, so an order that varies by filesystem makes
            # two runs of the same seed diverge on a different machine.
            return "\n".join(sorted(
                str(p.relative_to(self.root))
                for p in self.root.glob(str(arguments.get("glob", "**/*")))
                if p.is_file()))
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

    def _relative(self, path: str) -> str:
        """The checkout-relative form of a path the model supplied.

        A model that writes the same file once by relative path and once by
        absolute path produced two entries in ``changes``, so the record said
        two files changed when one had. Normalising here keeps the change set
        honest and keeps every write inside the checkout.
        """
        target = self._target(path)
        try:
            return str(target.resolve().relative_to(self.root))
        except ValueError:
            raise ValueError(f"{path} is outside the checkout") from None

    def _write(self, path: str, content: str, changes: list[dict]) -> str:
        path = self._relative(path)
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
                "rules": sorted({item.rule for item in verdict.findings}), "skipped": list(verdict.skipped)}
