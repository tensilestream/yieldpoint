"""A bound on how many times the per-edit gate may deny the same thing.

The Stop gate already has one: resumed once by itself, it reports and allows,
because an agent that cannot finish is worse than an unverified one. The
per-edit gate had no equivalent, and it is the surface where a loop is most
likely — it fires on every keystroke-sized change, and a converging refactor
passes through states that are each individually wrong.

Two edits are enough to see it. Adding a call and adding its import is one
change to a person and two tool calls to an agent; judged separately the first
is a dangling reference, and an agent that responds by adding the import can be
denied again for whatever the intermediate state broke next. A capable model
escapes by batching the edits — often through a shell, where this gate cannot
see them at all, which is the quiet way a verifier stops verifying. A weaker
model has no such move, and simply stops making progress.

So: the same rules denying the same file repeatedly is not a stubborn agent, it
is a gate that has said all it usefully can. After the configured number of
attempts this releases the edit and says so, and the finding is left to the Stop
gate, which sees the whole working tree and cannot be routed around.

**Releasing is not forgiving.** The finding is still real and still reported;
what changes is who gets to act on it and when. Nothing here is written to the
metrics ledger — this is operational state about one session, not an
observation about the code.
"""

from __future__ import annotations

import json
from pathlib import Path

from .core.policy import Policy

#: Beside the other local state, and equally disposable. Deleting it costs one
#: extra denial, which is why it is never worth failing an edit to write.
DEFAULT_PATH = ".yieldpoint/editloop.json"


def _state_path(root: str | Path = ".") -> Path:
    from .core.locate import repository

    return repository(Path(root)) / DEFAULT_PATH


def key_for(session: str, path: str, rules) -> str:
    """Identify one repeated denial: same session, same file, same rules.

    The rules are part of the key on purpose. An agent that fixes the dangling
    reference and is then told about a weak assertion is making progress, and
    its budget should start again; an agent told the same thing a third time is
    not.
    """
    return f"{session}\t{path}\t{','.join(sorted(set(rules)))}"


def attempts(key: str, *, root: str | Path = ".") -> int:
    """How many times this exact denial has already been issued."""
    try:
        stored = json.loads(_state_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    return int(stored.get("count", 0)) if stored.get("key") == key else 0


def record(key: str, *, root: str | Path = ".") -> int:
    """Count this denial and return the running total. Never raises."""
    count = attempts(key, root=root) + 1
    target = _state_path(root)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"key": key, "count": count}),
                          encoding="utf-8")
    except OSError:
        pass
    return count


def clear(*, root: str | Path = ".") -> None:
    """Forget the run, so the next distinct denial starts from zero."""
    try:
        _state_path(root).unlink()
    except OSError:
        pass


def progressed(path: str, *, root: str | Path = ".") -> None:
    """An edit to this file went through, so the run on it is over.

    Only this file: an agent that is stuck on one file and meanwhile edits
    another has not made progress on the first, and resetting on any success
    anywhere would hand it an unbounded budget one unrelated edit at a time.
    """
    try:
        stored = json.loads(_state_path(root).read_text(encoding="utf-8"))
        if str(stored.get("key", "")).split("\t")[1:2] == [path]:
            clear(root=root)
    except (OSError, ValueError, IndexError):
        pass


def budget(policy: Policy | None) -> int:
    """How many identical denials are allowed before the gate stands down."""
    if policy is None:
        return 3
    return max(1, policy.loop_breaker.max_repeats_without_progress)


def released(count: int, policy: Policy | None) -> bool:
    """Whether this denial has been issued too often to issue again."""
    return count > budget(policy)


def release(verdict, change, policy, root: str | Path = ".", session: str = "") -> str:
    """Stand down when this gate has denied the same thing too often.

    Returns the notice to print, or ``""`` to deny as normal. Never raises: a
    failure to track a loop must not itself become one.
    """
    from .hook import immediate

    try:
        if not getattr(change, "usable", False):
            return ""
        rules = sorted({finding.rule for finding in immediate(verdict)})
        count = record(key_for(session, change.path, rules), root=root)
        return notice(count, rules) if released(count, policy) else ""
    except Exception:  # noqa: BLE001 - a broken loop-breaker must still allow work
        return ""


def notice(count: int, rules) -> str:
    """What the agent is told when the gate stands down, in its own words."""
    named = ", ".join(sorted(set(rules))) or "this finding"
    return (
        f"yieldpoint: allowing this edit — {named} has already blocked it "
        f"{count - 1} times, and repeating the same denial is not helping.\n"
        "The finding stands and has not been waived. Run `yieldpoint review` "
        "when the change is complete; the stop gate checks the whole working "
        "tree and will report it again if it is still there.\n"
    )


__all__ = ["DEFAULT_PATH", "key_for", "attempts", "record", "clear", "progressed",
           "budget", "released", "release", "notice"]
