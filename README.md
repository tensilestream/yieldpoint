# AegisFlow

**Proves an AI-authored change didn't pass by weakening the tests.**

```diff
- assert invoice.total == Decimal("42.00")
+ assert invoice.total is not None
```

The suite is green. Coverage is unchanged — the weaker assertion executes the same lines.
The linter is silent. Nothing in a normal toolchain reports this, because every tool in it
grades the code *as it now stands*, and this is a statement about what was **taken away**.

AegisFlow grades the transition. Deterministically, in microseconds, with no model call.

```
$ aegisflow check --path tests/test_invoice.py --before old.py --after new.py
REPAIR  1 finding(s)

  tests/test_invoice.py:3 in test_total  [assertion_monotonicity]
    Assertion on inv.total was weakened: eq -> non_null.
    fix: Re-assert inv.total at eq strength, or fix the code under test so the
         original assertion passes. Restore `assert inv.total == Decimal('42.00')`.
```

---

## Quick start

```sh
pip install aegisflow
```

### 1. Audit what you have (30 seconds)

```sh
aegisflow scan
```

Exits `0` when clean, `1` with findings. Add `--json` for CI, `--rule <name>` to narrow.

### 2. Stop an agent weakening a test, in your editor

```sh
aegisflow install-hook          # add --advisory to report without blocking
```

Registers a Claude Code `PreToolUse` hook. Start a new session; when the agent tries to
weaken an assertion in a protected test file, the edit is **denied** and the agent is told
which subject was downgraded and what to restore. Your existing `.claude/settings.json` is
backed up first.

### 3. Put it in your agent's graph

```python
from aegisflow.langgraph import verify_node, make_router, PASS, REPAIR, ESCALATE, BLOCK

builder.add_node("verify", verify_node(policy=".aegisflow.json"))
builder.add_edge("generate", "verify")
builder.add_conditional_edges("verify", make_router(max_repairs=3), {
    PASS:     "apply_patch",
    REPAIR:   "generate",       # prescription injected into state, zero extra tokens
    ESCALATE: "human_review",
    BLOCK:    "human_review",
})
```

Because the verifier sits on the edge between `generate` and `apply`, **enforcement is
topological**: the agent cannot route around it, because the graph does the routing. That
is a stronger guarantee than a hook, an MCP tool or a prompt rule, all of which need the
model's cooperation.

`pip install "aegisflow[langgraph]"` for the runnable example in
[`examples/`](./examples/langgraph_repair_loop.py).

### 4. Gate CI and commits

```sh
git diff --cached      | aegisflow check --diff -            # pre-commit
git diff origin/main...| aegisflow check --diff - --json     # CI
```

---

## What it checks

| Rule | Catches |
|---|---|
| `assertion_monotonicity` | An assertion removed, downgraded, or made unable to fail |
| `vacuous_assertion` | `assert True` and friends |
| `skip_marker` | A test newly skipped or xfailed |
| `disabled_assertion` | Failure swallowed by `except: pass`, or on a dead branch |
| `empty_test` | A test that asserts nothing |
| `dangling_reference` | A refactor that renamed a definition and left call sites behind |
| `export_removed` | A name dropped from `__all__` and defined nowhere else |
| `boundary_violation` | A layer importing what its zone forbids |
| `change_too_large` | A change too big for a human to actually review |
| `file_too_long`, `function_too_long`, `too_many_parameters`, `nesting_too_deep`, `complexity_too_high` | Maintainability limits |
| `duplicate_implementation` | Copy-paste, compared by structure so renaming does not hide it |
| `ci_check_removed`, `ci_check_disabled` | A CI job deleted, or a step neutered with `continue-on-error` or `\|\| true` |
| `generated_file_edited` | Hand-editing output the next build will discard |
| `lint.*` | Your own linters, opt-in — 24 tools across 7 ecosystems |

Every rule's severity is configuration: `pass`, `repair`, `escalate`, `block`, or `off`.

### Two properties that shape all of it

**Findings are differential.** A problem that existed before your change is not attributed
to it, so you can switch AegisFlow on in an existing repository without a wall of findings
nobody caused. `"greenfield": true` makes the limits absolute for a new project.

**Uncertainty never blocks.** Analysis that could be wrong — a third-party linter, a
lexical parse, a file whose generated half is missing — is marked and **structurally
prevented from blocking**, enforced in code rather than by convention. The hook fails open:
an unreadable payload, a timeout or a crash allows the edit. A verifier that blocks because
it got confused is one you would disable within a day.

---

## Why deterministic

The standard way to correct an agent is another model — an LLM-as-judge — or the agent's
own trial-and-error loop. Both cost tokens per round, take seconds, and return verdicts
that differ between runs.

AegisFlow returns the same verdict for the same input, every time, with no inference. That
is what makes it usable as a **blocking gate**: you cannot gate a pipeline on a judge that
flakes. It is also why the repair prescription is free — it is assembled from the verdict,
not generated.

It also detects **reward hacking**. If your agent's reward signal is "tests pass", that
signal is gameable: the agent can win by weakening the test. If you run an eval harness or
an RL loop over a coding agent, this is the check that tells you whether it solved the task
or gamed the benchmark.

---

## Configuration

Rules live in a repo-committed `.aegisflow.json`, so every engineer's agent inherits the
same policy. Teams add their own rules declaratively:

```json
"structure": {
  "custom": [
    {"name": "no_network_in_core", "path": "src/core/**",
     "forbid_import": "requests", "message": "The core must not reach the network."}
  ]
}
```

Declarative on purpose: config is repo-committed, so a rule that could name code to run
would mean cloning a repository executes it.

---

## Status and limits

**Alpha.** The engine, CLI, Claude Code hook, LangGraph adapter, diff/CI path and
repository audit all work and are covered by 453 tests. Read this before adopting:

- **Python only.** TypeScript and Java are designed but not built; other languages are
  reported as `skipped`, never silently passed.
- **Snapshot, property-based and heavily table-driven suites** are poorly served — counting
  assertions is not meaningful there.
- **Subject aliasing is a known false positive**: renaming `inv` to `invoice` reads as a
  lost subject. Pinned as a test so it cannot be forgotten.
- **The cost claim is unmeasured.** That the prescription costs zero model calls is a
  property of the architecture and holds. That repair loops therefore converge in fewer
  *total* calls against a real model has not been benchmarked, and is not claimed as a
  result.
- No performance figure appears anywhere in this project without a runnable benchmark
  behind it.

## Documentation

| Document | Contents |
|---|---|
| [PLAN_AND_POSITIONING.md](./PLAN_AND_POSITIONING.md) | Why this exists, who it is for, what was deliberately cut |
| [IMPLEMENTATION_STAGES.md](./IMPLEMENTATION_STAGES.md) | Build order, every stage and its gate |
| [RULES.md](./RULES.md) | Engineering standards for this codebase |
| [CHANGELOG.md](./CHANGELOG.md) | Release history |
| [RELEASING.md](./RELEASING.md) | How a release is cut |

## License

Apache-2.0
