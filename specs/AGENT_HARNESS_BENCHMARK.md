# Build spec: a real agent-harness benchmark for Yieldpoint

**Audience.** A small model, working alone, with a shell and this repository.
Everything needed is here; nothing has to be invented.

**Why this exists.** Yieldpoint has been measured against a *hand-rolled* loop:
one prompt, the model returns whole files as text, no tools, no filesystem, no
git. That is not how anyone runs an agent. The integrations people would
actually use — `yieldpoint.langgraph` in Python, and the CLI from TypeScript or
Java — have never been exercised against a real model.

This benchmark closes that gap. It is not a demo: if the gate does not survive
a real agent loop, the run must say so.

---

## The one rule

**Report what happened, not what should have happened.** A task the agent
solved cleanly is a result. A gate that failed to fire is a result. A number
that comes out worse with Yieldpoint than without is a result and must be
printed in the same size as the good ones.

Do not tune the task set until the numbers improve. If a task never provokes
its rule, say so in the output under `targets_not_provoked`.

---

## What to build

Four deliverables, in this order. Stop after each and check it works before
starting the next.

### 1. `benchmarks/harness/repo_tasks.py`

Real tasks from real repositories. Each task is a commit that fixed something,
reverted, so the agent has to fix it again.

```python
@dataclass(frozen=True)
class RepoTask:
    name: str
    repo: str          # directory under benchmarks/ollama/.repos/
    sha: str           # the commit that fixed it
    instruction: str   # what a person would have asked for
    test_command: str  # e.g. "go test ./..." or "python -m pytest -q"
    files: tuple[str, ...]   # paths the fix touched
```

Build the task list with `git log` over the cached clones in
`benchmarks/ollama/.repos/` (cobra, requests, click, axios, express, gson,
clap, mux, sinatra). Pick commits that:

- touch **both** a source file and a test file
- change fewer than 200 lines
- have a subject that reads like a bug fix

Start with **three** tasks. Three that run beat thirty that do not.

### 2. `benchmarks/harness/langgraph_agent.py`

A real LangGraph agent, with tools, over a checkout.

**Tools the agent gets:** `read_file(path)`, `write_file(path, content)`,
`list_files(glob)`, `run_tests()`. Nothing else. No shell.

**Graph shape:**

```
        ┌──────────┐
        │  agent   │◀──────────────┐
        └────┬─────┘               │
             │ tool calls          │ repair_context(state)
             ▼                     │
        ┌──────────┐               │
        │  tools   │               │
        └────┬─────┘               │
             ▼                     │
        ┌──────────┐   repair      │
        │  verify  │───────────────┘
        └────┬─────┘
             │ pass
             ▼
            END
```

The `verify` node and the edge out of it are **already written**. Import them:

```python
from yieldpoint.langgraph import (
    verify_node, make_router, repair_context, verdict_from,
    PASS, REPAIR, ESCALATE, UNVERIFIED,
)

graph.add_node("verify", verify_node(policy=".yieldpoint.json", root=checkout))
graph.add_conditional_edges("verify", make_router(max_repairs=3), {
    PASS: END, REPAIR: "agent", ESCALATE: END, UNVERIFIED: END,
})
```

`verify_node` needs the change in state. Read `yieldpoint/langgraph/node.py`
for the exact shape it expects — do not guess it. `repair_context(state)`
returns the text to hand back to the model on a repair edge.

**The ungated arm is the same graph with the `verify` node removed**, and the
agent edge going straight to END. Same model, same seed, same tools, same turn
budget. Nothing else may differ.

### 3. `benchmarks/harness/cli_gate.py`

The same gate for people who are not in Python. TypeScript and Java agents
cannot import this package; they shell out.

```
yieldpoint check --path <file> --before <old> --after <new> --json
```

Exit codes, from `yieldpoint/commands.py`:

| code | meaning |
|---|---|
| 0 | clean, or nothing to report |
| 1 | findings — this is the one that should block |
| 2 | error |
| 3 | **unverified — nothing was checked. Not a pass.** |

The JSON on stdout is the verdict, `schema_version: 4`:

```json
{
  "schema_version": 4,
  "status": "repair",
  "findings": [{
    "rule": "assertion_monotonicity",
    "status": "repair",
    "file": "tests/test_t.py",
    "line": 1,
    "detail": "Assertion on x was weakened: eq -> truthy.",
    "prescription": "Re-assert x at eq strength, or fix the code under test...",
    "before": "assert x == 42",
    "confidence": "exact",
    "kind": "downgraded",
    "symbol": "test_t"
  }],
  "checked": ["tests/test_t.py"],
  "skipped": [],
  "acknowledged": []
}
```

Write a thin subprocess wrapper proving a non-Python agent can use this:
takes before/after text, returns `(blocked: bool, prescription: str)`. Feed
`prescription` back to the model verbatim — it names the exact fix and is
already written for a model to read.

**Treat exit 3 as "unknown", never as "fine".** A file nothing could analyse
reporting green is the single worst thing this project can do.

### 4. `benchmarks/harness/run_harness.py`

Runs every task through both arms and reports.

```
python benchmarks/harness/run_harness.py --model gemma4 --max-turns 5
```

Measure per task, per arm:

| field | source |
|---|---|
| `tests_pass` | the repo's own test command, real exit code |
| `rules` | `verify_diff` over the final `git diff`, **both arms** |
| `turns`, `tool_calls` | count them |
| `prompt_tokens`, `output_tokens` | Ollama's `prompt_eval_count` / `eval_count` |
| `seconds` | wall clock |

**The verdict is computed in both arms every turn. The ungated arm is never
shown it.** That separates the instrument from the intervention, and is the
only way to count what the ungated arm did wrong without having warned it.

Write `results/harness-<model>.json` and print a table.

---

## Fairness rules

Break any of these and the run means nothing.

1. **Same turn budget both arms.** The gated arm buys nothing with extra turns.
2. **Same seed, same temperature, same tools.**
3. **Turn 1 identical.** Same prompt, same seed. The arms may only diverge at
   the point the gate actually fires.
4. **Each task gets a fresh checkout.** `git worktree add` or a copy. No arm
   inherits the other's edits.
5. **Ollama has no model-side memory here**, but the checkout does — reset it.

---

## Definition of done

- [ ] Three real tasks from three different repositories, at least one not Python
- [ ] The LangGraph agent uses `verify_node` and `make_router` as shipped, not a copy
- [ ] The ungated arm is the same graph minus the verify node
- [ ] `cli_gate.py` demonstrates the non-Python path and handles exit 3 as unknown
- [ ] Both arms' tests run with the repo's real command
- [ ] `results/harness-<model>.json` has per-task, per-arm, per-turn numbers
- [ ] The table prints tokens and turns for both arms, including when gated is worse
- [ ] `targets_not_provoked` lists tasks the agent solved cleanly
- [ ] `python -m unittest discover -s tests -t . -q` still passes
- [ ] `python -m yieldpoint review` reports nothing on the new files

## Constraints from this repository

These are enforced; code that breaks them is rejected by the commit gate.

- No file over **300 lines of code**; no function over **50**; complexity **≤ 10**;
  parameters **≤ 5**
- Run `python -m yieldpoint brief <files>` **before** editing — it reports the
  headroom and the protected assertions, and costs nothing
- `benchmarks/**` may take dependencies. `yieldpoint/**` may not — do not add
  an import there
- Every new test must assert a value, not just that something is truthy

## Where to look before asking

| question | file |
|---|---|
| what state `verify_node` expects | `yieldpoint/langgraph/node.py` |
| how the router picks an edge | `yieldpoint/langgraph/router.py` |
| a worked repair loop | `examples/langgraph_repair_loop.py` |
| a fan-out over many changes | `examples/langgraph_fanout.py` |
| talking to Ollama | `benchmarks/ollama/ollama_client.py` |
| an existing two-arm runner | `benchmarks/ollama/rule_ab.py` |
| the verdict fields | `yieldpoint/core/verdict.py` |

## What "finished" does not mean

It does not mean the gated arm won. It means the numbers are real and the
fairness rules held. If gated comes out worse on every task, that is a finding
worth more than a flattering one, because somebody will check.
