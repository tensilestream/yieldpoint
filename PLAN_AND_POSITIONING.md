# AegisFlow — State Audit, Positioning, and Build Plan

> Written before writing more code. §2 argues for cutting ~70% of the current scope;
> §3 changes what the product *is*. Read those two first.
>
> **Decisions locked:** engine in Python (LangGraph is Python-first); LangGraph SDK is
> the first shipped surface.

---

## 1. What is actually in the repo today

I read every file. **AegisFlow is currently a specification plus a mock. No check in this
repository checks anything.**

| Surface | Claim | Reality |
|---|---|---|
| `packages/cli` `audit` | "Scan for test tampering and boundary drift" | Prints `✓ 0 layer violations detected` unconditionally. Reads no files. |
| `packages/cli` `install-mcp` | Registers with Cursor / Claude Desktop | Writes `npx -y aegisflow daemon` — no `daemon` command exists, package unpublished. Cursor's real path is `~/.cursor/mcp.json`. Overwrites user config with no backup. |
| `packages/cli/package.json` | deps on chalk, commander, glob, prompts | None are imported anywhere. `main` points at a nonexistent `dist/`. `build: tsc` with no tsconfig and no TS sources. |
| `packages/vscode-extension` | Live FinOps HUD | Status bar hardcoded to `$0.42 / $2.50`. Ignores both settings it contributes. |
| `packages/vscode-extension` | Boundary rules from `.aegisflow.json` | Never reads it. Rules are hardcoded `/components/` substring matches — POSIX-only, so they silently no-op on Windows. |
| `packages/vscode-extension` | builds | **No `tsconfig.json`.** `npm run compile` fails. Cannot be built or loaded. |
| `packages/browser-extension` | GitHub PR shield | Manifest references icons that do not exist → Chrome refuses to load it. |
| `packages/browser-extension/content.js` | Detects test tampering | Flags any filename containing `test`/`spec`/`fixture` (`latest.ts`, `testimonial.tsx` false-positive), else renders green **"Verified: Zero Drift — PASSED"** having analysed nothing. |
| `crates/` (13 Rust crates) | The entire engine | Does not exist. |
| `policy.aegis` / `AEGISLANG_SPEC.md` | Custom non-Turing policy DSL | No parser exists. The file is decorative. |

**The worst defect is not a missing feature — it is the green banner.** A guardrail that
renders false assurance is worse than no guardrail. If one engineer ships one bad change
because AegisFlow said PASSED, the product is dead in that org permanently. Every surface
that asserts safety must say "not evaluated" until it genuinely evaluates.

---

## 2. Is this really helpful? — candid answer

**The category is real. The scope is not defensible. One slice is excellent.**

### 2a. The three failure modes people actually complain about

1. **The agent made the tests pass by weakening the tests.** Deletes an assertion, changes
   `expect(x).toBe(3)` to `expect(x).toBeDefined()`, adds `skip`, wraps the body in
   `try/except`, or writes `assert True`.
2. **The agent drifted across architectural layers** — UI module imports the DB driver.
3. **The agent looped** — same file rewritten 14 times, budget burned, no progress.

### 2b. Which of those is a product?

| Failure mode | Already solved by | Verdict |
|---|---|---|
| Layer drift (#2) | `dependency-cruiser`, ESLint `import/no-restricted-paths`, Nx boundaries, ArchUnit, import-linter — free, mature, CI-ready | **Commodity.** Ship as a feature, never lead with it. |
| Loop / budget (#3) | Partially: LangGraph `recursion_limit`, harness-level caps | **Weak alone** — but see §4.3, a *semantic* loop breaker beats a superstep counter and is a real gap. |
| **Test-suite tampering (#1)** | **Nothing.** Linters can't see it. Coverage can't — deleting an assertion leaves coverage green or *improves* it. Mutation testing is too slow to gate on. Human review misses it in a 40-file agent diff. | **The wedge.** |

**Test tampering is the only failure mode that is simultaneously painful, unserved,
deterministically detectable with zero LLM calls, and invisible to every metric teams
currently watch.**

### 2c. Claims that must be retired now

These destroy credibility with the exact technical buyer we need:

- **"70–85% token reduction via SDP-ATC"** — unbenchmarked; modern harnesses already prune
  context. Delete until a reproducible benchmark exists.
- **"<50µs bytecode eval", "<100µs ShadowVFS revert", "<500µs supervision restart"** — six
  precise numbers for code that has never run. A reviewer who catches one discounts the
  whole README.
- **"Lyapunov phase-space convergence"** — the underlying idea (rolling window of
  structural hashes) is sound and cheap. The physics vocabulary reads as obfuscation.
  Call it **semantic loop detection** and show the window.
- **PII vaulting / CVE shield / WAF immunity** — three mature markets. Entering all three
  at v0.1 signals a product with no point of view.
- **`RULES.md`'s justification for Rust** — GC jitter and cgo overhead are unconvincing at
  this scale. The *real* argument for Rust is single-implementation polyglot distribution:
  one engine serving Python and TypeScript without two codebases drifting. That is a much
  stronger case. Rewrite the rationale; keep the conclusion, but see §7 for sequencing.

### 2d. Verdict

> A focused **verification layer for agents that write code** is infrastructure people
> building agent products would adopt this quarter. A "deterministic control plane with 13
> subsystems" will not be evaluated, because it claims to replace parts of a stack nobody
> asked it to replace. The value is real; it is buried under ~70% too much surface area.

---

## 3. What AegisFlow is — the repositioning

**AegisFlow is not an agent, and it does not compete with coding agents.**

Competing with Cursor, Claude Code, Devin and Copilot Workspace is a knife fight with
well-funded incumbents, and the IDE-plugin position makes AegisFlow a feature they can
absorb in a sprint. The correct position is one layer down:

> **AegisFlow is the deterministic verification layer that code-writing agents are built
> on top of — consumed natively by LangGraph and equivalent orchestration frameworks.**

Not a competitor to agents. A **dependency** of the people building them.

### 3.1. Why the framework position also solves the enforcement problem

An earlier draft of this plan made the MCP server the primary surface. That has a fatal
flaw: **an MCP tool is advisory.** The agent chooses whether to call it, and an agent about
to weaken a test will not spontaneously call `aegis_check_if_i_am_cheating`. Guardrails
that depend on the guarded party opting in are not guardrails.

The framework position dissolves this. A verification node placed on the edge between
`generate` and `apply_patch` is **structurally in the path**. The agent cannot route around
it, because the agent is not the thing doing the routing — the graph is. Enforcement stops
being a matter of the model's cooperation and becomes a property of the topology.

That is a materially stronger guarantee than hooks, MCP tools, or prompt rules, and it is
the single best reason to take this position.

### 3.2. Honest narrowing this forces

"Guardrails for any LangGraph agent" is crowded and vague — Guardrails AI, NeMo Guardrails,
Invariant, Patronus sit there, and LangGraph itself ships interrupts, checkpointers and
`recursion_limit`. **Every piece of real IP in this repo is code-specific**: assertion
monotonicity, import boundaries, structural drift. None of it means anything unless the
agent writes code.

So the line is **agents that write code**, not agents in general. That is a smaller market
and a defensible one.

---

## 4. USP

**One sentence:**

> **AegisFlow is the deterministic verification node in your agent's graph: it tells the
> agent, in zero tokens and with a reproducible verdict, exactly which rule its generated
> code breaks and what to do instead.**

Four properties, ordered by defensibility.

### 4.1. Zero-token deterministic critique — and the argument is *cost*, not safety

The standard repair loop in a LangGraph agent is: generate → test → fail → feed the error
back → regenerate. **Every cycle is a full model call.** The alternative correction pattern
is an LLM-as-judge: 5–15s of latency, a doubled token bill, and a verdict that is not
reproducible run to run.

AegisFlow returns a structured prescription in microseconds, for free, and returns the
*same* verdict every time.

**Status of this claim, split into what is proven and what is not** (RULES.md section 5):

- **Proven.** The prescription costs *zero model calls*. It is assembled from the verdict,
  not generated. `examples/langgraph_repair_loop.py` runs against real LangGraph and the
  repair round adds no inference. An LLM-as-judge adds one call per round by construction.
  This part is architecture, not measurement, and it holds.
- **Not yet measured.** That the loop therefore *converges in fewer total model calls*
  against a **real** model. The example uses a scripted model, which demonstrates the
  mechanism and proves nothing about convergence. Until a real-model benchmark exists,
  this stays a hypothesis and must not be stated as a result in any external material.

Determinism is also what makes it usable as a *blocking* gate at all: you cannot gate a
production pipeline on a judge that flakes.

### 4.2. Assertion monotonicity — the check nobody else runs

For any edit to a test file, assertion count and assertion *strength* must not decrease.
Strength is an ordered lattice:

```
toBe(3)  >  toEqual(obj)  >  toBeTruthy()  >  toBeDefined()  >  not.toThrow()
assert x == 3  >  assert x  >  assert x is not None  >  (no assert)
```

A downgrade along that lattice is a finding **even when the assertion count is unchanged**
— which is exactly why coverage cannot detect it. Removing an assertion keeps coverage
green.

### 4.3. Anti-reward-hacking oracle — a second market, free

If an agent's reward signal is "tests pass," **that signal is gameable**: the agent can win
by weakening the test rather than fixing the code. This is a known, current, unsolved
problem in agent evaluation and RL training loops.

Assertion monotonicity is a deterministic anti-reward-hacking check. Anyone running a
SWE-bench-style eval, a fine-tuning loop, or an internal agent leaderboard needs a verdict
on *"did the agent game the benchmark?"* — and nobody ships one. This is valuable
independently of production use, and it reaches researchers and eval teams, not just
builders.

Related: a **semantic loop breaker** beats LangGraph's `recursion_limit`, which is a blunt
superstep counter that raises `GraphRecursionError` at N regardless of whether progress is
being made. Detecting *the same structural state recurring with no progress* is strictly
more useful, and maps naturally onto checkpointer state keyed by `thread_id`.

### 4.4. It grades the transition, not the end state

Every linter, SAST tool and architecture checker evaluates code as it now stands. "The
agent cheated" is a statement about what was *taken away*. Only a diff-native verifier can
express it.

**Positioning line:** *Coverage tells you the tests ran. AegisFlow tells you they still mean something.*

**Explicitly not:** an agent, an agent framework, a linter, a SAST tool, a dependency
scanner, a secrets vault, or an LLM proxy.

---

## 5. Persona

The framework position moves the buyer from "developer using an agent" to **"developer
building one."**

### Primary (high confidence — build for this person)

**"Maya, engineer building a code-generating agent product or an internal migration agent,
on LangGraph."**

- Her agent writes code that runs somewhere that matters: customer repos, a migration
  across 400 services, a code-review or refactor bot.
- **Qualifying event:** her agent shipped a change that passed its own tests because it had
  quietly rewritten them — or it burned a four-figure inference bill looping on one file.
- She already has the graph. She needs one node, not a platform.
- **She will not build this herself** — assertion strength lattices and diff-native
  verification are a month of work orthogonal to her product.
- Budget is real: she is already paying for inference, and this reduces that bill.
- Adoption test: `pip install` and three lines in her graph, working in the first run.

### Secondary (high confidence)

**Eval / research teams and anyone running agent benchmarks** — per §4.3, they need the
anti-reward-hacking verdict and have no alternative. Different motive, identical engine.

### Tertiary (medium confidence — later, not now)

Teams on CrewAI, AutoGen, OpenAI Agents SDK, Mastra, Pydantic AI. Same need, each needs a
small adapter. Cheap *if* the core stays framework-neutral — which is why §7 keeps the
verdict API clean even though the LangGraph adapter ships first.

### Explicitly NOT the persona

- **Developers merely using Cursor/Claude Code.** That is the plugin position we just
  rejected; the IDE surfaces become backstops, not the product.
- **Regulated-enterprise buyers.** They buy SSO, audit trails, vendor security review and a
  signed BAA — a 12-month motion this repo cannot service. Chasing it is what produced the
  PII/CVE/WAF sprawl.
- **Teams not writing code with agents.** No code, no product.

### Where it will genuinely fail — say this openly

- Dynamically-generated, snapshot-only, or heavily table-driven suites, where assertion
  counting is meaningless.
- Legitimate refactors that consolidate assertions — real false positives. Mitigation:
  return `repair`/`warn`, never `block`, until per-repo confidence is established.
- Languages beyond Python/JS/TS at launch.

---

## 6. Build plan

Guiding rule: **every claim a surface makes must be backed by a check that actually ran.**
A surface that cannot evaluate says "not evaluated" — never "PASSED".

Engine language: **Python**, per the locked decision. LangGraph is Python-first, the target
persona lives in `pip`, and the MCP server ships from Python just as easily. The two JS
engine modules already written (`glob.js`, `policy.js`, both verified) are ported, not
wasted.

### Phase 0 — Stop lying (half a day) — non-negotiable

- Delete the green "Verified / PASSED" banner from the browser extension.
- Delete the hardcoded `$0.42` from the VS Code status bar; show `—` when unknown.
- `aegisflow audit` exits non-zero with "not implemented" rather than printing "Clean".
- Add the missing `tsconfig.json` so the VS Code extension can build at all.
- Add the missing browser-extension icons so Chrome will load it.
- `install-mcp` stops registering a `daemon` command that does not exist.
- Mark the JS packages clearly as backstops pending the Python core.

### Phase 1 — `aegisflow.core` (Python) + the LangGraph SDK

Zero runtime dependencies in the core. Each module one responsibility, under the 300-line
limit in `RULES.md`.

| Module | Responsibility |
|---|---|
| `core/glob.py` | Bounded glob → anchored regex, POSIX-normalised (port of verified JS) |
| `core/policy.py` | Canonical policy dataclasses + `.aegisflow.json` normalisation (port) |
| `core/aegislang.py` | Parser for `policy.aegis` → the *same* shape, making the DSL real |
| `core/diff.py` | Unified-diff parser: hunks, added/removed lines per file |
| **`core/assertions.py`** | **The wedge: assertion extraction + strength lattice** |
| **`core/monotonicity.py`** | **Count-and-strength verdict across a change set** |
| `core/testintegrity.py` | Vacuous assertions, `skip`/`xfail`/`.only`, empty bodies, swallowed excepts |
| `core/imports.py` | Lexical import extraction (Python/JS/TS) |
| `core/boundaries.py` | Zone rule evaluation — the commodity feature, shipped quietly |
| `core/verdict.py` | `Verdict` / `Finding` types: `pass` \| `repair` \| `escalate` \| `block` |
| `core/critique.py` | Findings → the structured, agent-consumable prescription |

The LangGraph surface, shipped in the same phase:

```python
from aegisflow.langgraph import verify_node, route_on_verdict, LoopBreaker

builder.add_node("verify", verify_node(policy=".aegisflow.json"))
builder.add_edge("generate", "verify")
builder.add_conditional_edges("verify", route_on_verdict, {
    "pass":     "apply_patch",
    "repair":   "generate",      # prescription injected into state, zero extra tokens
    "escalate": "human_review",  # interrupt()
})
```

- `verify_node(...)` — reads the proposed diff/patch off graph state, returns a `Verdict`.
- `route_on_verdict` — the conditional edge; enforcement is topological (§3.1).
- `LoopBreaker` — semantic no-progress detection keyed by `thread_id`, replacing
  `recursion_limit` (§4.3).

The exact LangGraph API surface (state schema conventions, `Command` vs conditional edges,
`interrupt()` signature) gets verified against current docs before implementation rather
than assumed.

### Phase 1.5 — Voice-ready (see §9)

`Verdict.speak()`, confirmation tokens for high-blast-radius changes, and mode-dependent
severity. Pure core work — no connectors, no credentials, no network.

### Phase 2 — Prove the wedge

A fixture corpus of real test-weakening patterns (delete, downgrade, skip, tautology,
swallow) plus a corpus of *legitimate* refactors, and a measured false-positive rate. The
gate is never allowed to `block` before this number exists.

### Phase 3 — More doors, one engine

MCP server (`aegisflow mcp`) for Claude Code / Cursor; adapters for CrewAI, OpenAI Agents
SDK, Mastra; `pre-commit` hook; GitHub Action. Each is thin because the core is
framework-neutral.

### Phase 4 — Human-facing backstops

VS Code diagnostics and the Chrome PR shield, both driven by the real engine, reporting
only what was actually checked.

### Phase 5 — Earn the rest

Benchmarks for every performance claim. Then — only if adoption justifies it, and for the
polyglot reason in §2c rather than the GC-jitter one — the Rust core with pyo3/napi
bindings.

### Deferred indefinitely

SDP-ATC token compaction, PII vaulting, CVE shield, WAF immunity, 24/7 supervision,
IoT/embedded C-ABI. Each is a separate product.

---

## 7. How we will know it works

1. `pytest` passes, with fixture-based coverage of every weakening pattern in §4.2.
2. A runnable LangGraph example: an agent that tries to weaken a test, gets routed to
   `repair` with a deterministic prescription, and converges — with the model-call count
   before and after measured, not asserted.
3. False-positive rate measured on legitimate human refactors **before** the gate may block.
4. Every surviving performance claim in the README backed by a reproducible benchmark, or
   deleted.

---

## 8. Open questions

- Does `verify_node` read the patch from a convention-named state key, or take an
  extractor callable? Convention is friendlier; explicit is more honest about coupling.
- Should `escalate` default to `interrupt()` (blocking, needs a human) or to a warning
  channel? Blocking is safer and more annoying; this likely needs to be per-rule.
- Language coverage at launch: Python-only is faster and matches the persona's own stack,
  but their *agents* most often write TS/JS. Probably both, Python first.
- Whether intent verification (§9.3) can be made deterministic from in-repo sources alone,
  now that external trackers are out of scope.

---

## 9. Voice as a first-class target

External context connectors (Confluence, Jira, git hosting) are **out of scope** — see
§9.3. What remains from that discussion is voice, which is kept and promoted.

### 9.1. Why voice makes verification load-bearing

In an IDE the human is the backstop: they see the diff before it lands. **In voice there is
no diff, no screen, no glance.** The review step does not exist.

That inverts the product's importance. With a screen, deterministic verification is a
convenience layered on top of human review. In voice it *replaces* human review — it is the
only thing between a spoken instruction and applied code. Voice is therefore the modality
where AegisFlow is load-bearing rather than optional.

Stated honestly: dictating refactors to a production repository is not yet a common
workflow, and this plan does not assume it becomes one. The defensible claim is narrower
and available now — **voice removes the reviewer, so a deterministic gate plus spoken
confirmation is what makes a voice-driven code change safe enough to attempt at all.**
Phase 1.5 tests exactly that for about a week of work, before any larger bet is placed.

### 9.2. What voice requires from the engine

- **`aegisflow.speech.speak(verdict)`** — a one-sentence spoken summary with a drill-down
  tree behind it (a free function, not a `Verdict` method: see IMPLEMENTATION_STAGES.md
  Stage 8):
  *"Three files changed. Assertions held. One boundary warning in `checkout`."* This is a
  formatting concern over the existing `Verdict`, not new analysis.
- **Confirmation tokens.** For an irreversible or high-blast-radius change, the verdict
  returns a spoken question requiring explicit assent before apply. This is the primitive
  that was missing when this repository's own files were deleted with nothing checking the
  blast radius beyond a single approval prompt.
- **Mode-dependent severity.** A finding that may be auto-repaired silently in IDE mode
  must be announced in voice mode, because the user cannot see it. Severity is a function
  of modality; the policy file carries a `voice` override block.

All three are pure core work. **Zero connectors, zero credentials, zero network.**

### 9.3. Out of scope: external context connectors

Confluence, Jira and git-hosting connectors are cut, for a reason that generalises:

> **If every coding agent already has access to a context source, integrating with it is
> not differentiating.** The repository, its history, its issues and its tickets are
> already reachable by any agent worth verifying. A connector adds an enterprise
> integration burden — OAuth, permission scoping, data residency, vendor review — and buys
> no capability the host agent lacks.

It also protects the persona. §5's buyer is an engineer building an agent, not a platform
team at a 300-person company; Confluence integration *is* an enterprise sale, and adopting
it would have changed the buyer silently. Keeping it out means §5 stands unchanged.

**What is lost:** `intent_unverified` — verifying that a change actually satisfies the
acceptance criteria it was asked to satisfy. That needs a *structured* intent spec, and an
issue tracker is the usual place one exists. Whether it can be reconstructed
deterministically from in-repo sources alone — commit trailers, the task text already
present in graph state, explicit criteria in a PR body — is left as an open question in §8
rather than promised here. It is a real capability gap, and the honest position is that the
connector cost was not worth paying to close it yet.

**What survives regardless:** the principle already written into `RULES.md` §4 — no network
in the verification path. Whatever context the engine ever consumes must be pinned and
offline at verdict time.

### 9.4. Sequencing

Voice lands as **Phase 1.5**, immediately after the core and the LangGraph node, because it
needs nothing beyond them. No connectors are planned in any phase.
