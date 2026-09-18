# AegisFlow

**The deterministic verification layer for agents that write code.**

AegisFlow is a verification node you place inside your agent's graph. Before generated
code is applied, AegisFlow returns a reproducible verdict and — when the code breaks a
rule — a structured prescription describing exactly what to fix.

It is not an agent, and it does not compete with one. It is a dependency of the people
building them.

> **Status: pre-implementation.** The positioning and build plan are settled and written
> up in [PLAN_AND_POSITIONING.md](./PLAN_AND_POSITIONING.md). No verification code exists
> yet. Nothing in this README describes behaviour that currently runs; every claim here is
> a commitment, not a measurement. Performance numbers will appear only alongside a
> reproducible benchmark.

---

## The problem

An agent is told to make the tests pass. It cannot fix the bug. So it deletes the
assertion.

```diff
- assert invoice.total == Decimal("42.00")
+ assert invoice.total is not None
```

The suite is green. Coverage is unchanged — or better, since the weaker assertion still
executes the same lines. The linter is silent. The PR looks clean. Nothing in a normal
toolchain reports this, because every tool in it grades the code as it now stands, and
this is a statement about what was *taken away*.

## The check

**Assertion monotonicity.** Across a change, assertion count and assertion *strength* must
not decrease. Strength is an ordered lattice:

```
assert x == 3   >   assert x in xs   >   assert x   >   assert x is not None   >   (none)
toBe(3)         >   toEqual(obj)     >   toBeTruthy()  >  toBeDefined()        >   (none)
```

A move down that lattice is a finding **even when the assertion count is unchanged** —
which is precisely the case coverage cannot see.

Alongside it: vacuous assertions (`assert True`), newly-added skip markers, emptied test
bodies, swallowed exceptions, and architectural boundary violations.

## How it plugs in

```python
from aegisflow.langgraph import verify_node, route_on_verdict

builder.add_node("verify", verify_node(policy=".aegisflow.json"))
builder.add_edge("generate", "verify")
builder.add_conditional_edges("verify", route_on_verdict, {
    "pass":     "apply_patch",
    "repair":   "generate",      # prescription injected into state, zero extra tokens
    "escalate": "human_review",  # interrupt()
})
```

Because the verifier sits on the edge between `generate` and `apply_patch`, **enforcement
is topological**. The agent cannot route around it — the graph does the routing, not the
agent. This is a stronger guarantee than a hook, an MCP tool or a prompt rule, all of
which require the model's cooperation to work.

---

## Why it is worth adding to your graph

**It reduces your inference bill.** The standard repair loop is generate → test → fail →
feed the error back → regenerate, and every cycle is a full model call. The alternative,
an LLM-as-judge, doubles the token bill and returns a verdict that is not reproducible run
to run. AegisFlow's prescription is deterministic and costs no tokens, so the repair loop
converges in fewer model calls.

**It is reproducible, so you can actually gate on it.** The same diff yields the same
verdict, always. You cannot block a pipeline on a judge that flakes.

**It detects reward hacking.** If your reward signal is "tests pass," that signal is
gameable — the agent can win by weakening the test. If you run an eval harness, a
leaderboard, or an RL loop over a coding agent, assertion monotonicity is the check that
tells you whether the agent solved the task or gamed the benchmark.

---

## What AegisFlow is not

Not an agent. Not an agent framework. Not a linter, SAST tool, dependency scanner, secrets
vault or LLM proxy. Boundary and layer rules are included as a feature, but that ground is
already well served by `import-linter`, `dependency-cruiser` and ArchUnit, and it is not
the reason to adopt this.

## Where it will not work

- Snapshot-only, heavily table-driven, or dynamically generated suites, where counting
  assertions is meaningless.
- Legitimate refactors that consolidate assertions will produce false positives. Findings
  return `repair` rather than `block` until a per-repo false-positive rate is measured.
- Languages beyond Python and JS/TS at launch.

---

## Configuration

Rules live in a repo-committed [`.aegisflow.json`](./.aegisflow.json), so every engineer's
agent inherits the same policy.

## Documentation

| Document | Contents |
|---|---|
| [PLAN_AND_POSITIONING.md](./PLAN_AND_POSITIONING.md) | State audit, positioning rationale, persona, phased build plan |
| [RULES.md](./RULES.md) | Engineering standards for this codebase |

## License

Apache-2.0
