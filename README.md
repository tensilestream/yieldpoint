<h1 align="center">AegisFlow</h1>

<p align="center">
  <strong>Proves an AI-authored change didn't pass by weakening the tests.</strong>
</p>

<p align="center">
  <a href="https://pypi.org/project/aegisflow/"><img alt="PyPI" src="https://img.shields.io/pypi/v/aegisflow.svg"></a>
  <a href="https://pypi.org/project/aegisflow/"><img alt="Python versions" src="https://img.shields.io/pypi/pyversions/aegisflow.svg"></a>
  <a href="https://github.com/tensilestream/AgeisFlow/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/tensilestream/AgeisFlow/actions/workflows/ci.yml/badge.svg"></a>
  <a href="./LICENSE"><img alt="License" src="https://img.shields.io/badge/license-Apache--2.0-blue.svg"></a>
  <img alt="Dependencies" src="https://img.shields.io/badge/runtime%20deps-0-brightgreen.svg">
</p>

---

```diff
- assert invoice.total == Decimal("42.00")
+ assert invoice.total is not None
```

The suite is green. Coverage is unchanged — the weaker assertion executes the same lines.
The linter is silent. Nothing in a normal toolchain reports this, because every tool in it
grades the code *as it now stands*, and this is a statement about what was **taken away**.

AegisFlow grades the transition. Deterministically, in microseconds, with no model call.

```console
$ aegisflow check --path tests/test_invoice.py --before old.py --after new.py
REPAIR  1 finding(s)

  tests/test_invoice.py:3 in test_total  [assertion_monotonicity]
    Assertion on inv.total was weakened: eq -> non_null.
    fix: Re-assert inv.total at eq strength, or fix the code under test so the
         original assertion passes. Restore `assert inv.total == Decimal('42.00')`.
```

## Contents

- [Install](#install) · [Quick start](#quick-start) · [Editor setup (MCP)](#editor-setup-mcp)
- [LangGraph](#use-it-in-your-agents-graph) · [CI and pre-commit](#gate-ci-and-commits)
- [What it checks](#what-it-checks) · [Configuration](#configuration)
- [Why deterministic](#why-deterministic) · [Status and limits](#status-and-limits)
- [Contributing](#contributing) · [License](#license)

---

## Install

```sh
pip install aegisflow                 # the engine and CLI, zero dependencies
pip install "aegisflow[langgraph]"    # plus the LangGraph example's requirements
```

Requires Python 3.10 or newer. Nothing else — the verification core has no runtime
dependencies, makes no network calls, and never invokes a model.

<details>
<summary>Other install methods</summary>

```sh
pipx install aegisflow                            # isolated CLI
uv tool install aegisflow                         # same, via uv
pip install git+https://github.com/tensilestream/AgeisFlow    # from source
```
</details>

## Quick start

### 1. Audit what you already have — 30 seconds

```sh
aegisflow scan
```

Exits `0` when clean, `1` with findings. Add `--json` for CI, `--rule <name>` to narrow.

### 2. Stop an agent weakening a test, in your editor

```sh
aegisflow install-hook          # add --advisory to report without blocking
```

Registers a Claude Code `PreToolUse` hook. Start a new session; when an agent tries to
weaken an assertion in a protected test file, the edit is **denied** and the agent is told
which subject was downgraded and what to restore. Your `.claude/settings.json` is backed up
first.

### 3. Verify a change by hand

```sh
aegisflow check --path tests/test_invoice.py --before old.py --after new.py
git diff --cached | aegisflow check --diff -
```

---

## Editor setup (MCP)

AegisFlow ships an [MCP](https://modelcontextprotocol.io) server, so any MCP-speaking
editor or agent can ask it for a verdict.

```sh
aegisflow install-mcp --list                    # what can be configured
aegisflow install-mcp --client cursor           # write the config
aegisflow install-mcp --client zed --show       # print it instead, to paste yourself
```

| Client | Scope | Configuration file |
|---|---|---|
| Claude Code | project | `.mcp.json` |
| Claude Desktop | user | `claude_desktop_config.json` |
| Cursor | user | `~/.cursor/mcp.json` |
| Windsurf | user | `~/.codeium/windsurf/mcp_config.json` |
| VS Code | project | `.vscode/mcp.json` |
| Zed | user | `~/.config/zed/settings.json` |

Most clients take this shape:

```json
{
  "mcpServers": {
    "aegisflow": { "command": "aegisflow", "args": ["mcp"] }
  }
}
```

<details>
<summary>VS Code and Zed use different shapes</summary>

```json
// .vscode/mcp.json
{ "servers": { "aegisflow": { "type": "stdio", "command": "aegisflow", "args": ["mcp"] } } }
```

```json
// ~/.config/zed/settings.json
{ "context_servers": { "aegisflow": { "command": { "path": "aegisflow", "args": ["mcp"] } } } }
```
</details>

Tools offered: `aegis_verify_change`, `aegis_verify_diff`, `aegis_scan`, `aegis_policy`.

> **MCP explains; it does not enforce.** An MCP tool is one the agent *chooses* to call, so
> an agent intent on weakening a test will simply not ask. Use it so a blocked agent can
> find out *why* without burning tokens guessing — and use the hook, pre-commit or the
> LangGraph node for anything that must actually hold.

Vendors move these paths and formats between releases. `--show` prints the snippet if the
writer is out of date; `aegisflow mcp` is the part that matters and can always be wired up
by hand.

---

## Use it in your agent's graph

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

The adapter imports nothing from LangGraph — a node is a callable — so it works with any
graph library using the same convention. Runnable example:
[`examples/langgraph_repair_loop.py`](./examples/langgraph_repair_loop.py).

## Gate CI and commits

```sh
git diff --cached       | aegisflow check --diff -           # pre-commit
git diff origin/main... | aegisflow check --diff - --json    # CI
```

A ready-made [`.pre-commit-config.yaml`](./.pre-commit-config.yaml) is included.

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
| `ci_check_removed`, `ci_check_disabled` | A CI job deleted, or a step neutered with `continue-on-error` or `\|\| true` |
| `change_too_large` | A change too big for a human to actually review |
| `file_too_long`, `function_too_long`, `too_many_parameters`, `nesting_too_deep`, `complexity_too_high` | Maintainability limits |
| `duplicate_implementation` | Copy-paste, compared by structure so renaming does not hide it |
| `generated_file_edited` | Hand-editing output the next build will discard |
| `lint.*` | Your own linters, opt-in — 24 tools across 7 ecosystems |

Every rule's severity is configuration: `pass`, `repair`, `escalate`, `block`, or `off`.

Assertion styles understood: bare `assert`, `unittest`, assertpy, AssertJ, Jest, Chai and
Hamcrest matchers. Migrating between them is not a weakening.

### Two properties that shape all of it

**Findings are differential.** A problem that existed before your change is not attributed
to it, so you can switch AegisFlow on in an existing repository without a wall of findings
nobody caused. `"greenfield": true` makes the limits absolute for a new project.

**Uncertainty never blocks.** Analysis that could be wrong — a third-party linter, a
lexical parse, a file whose generated half is missing — is marked and **structurally
prevented from blocking**, enforced in code rather than by convention. The hook fails open:
an unreadable payload, a timeout or a crash allows the edit. A verifier that blocks because
it got confused is one you would disable within a day.

## Configuration

Rules live in a repo-committed `.aegisflow.json`, so every engineer's agent inherits the
same policy. Teams add their own rules declaratively:

```json
{
  "structure": {
    "greenfield": true,
    "custom": [
      {"name": "no_network_in_core", "path": "src/core/**",
       "forbid_import": "requests", "message": "The core must not reach the network."}
    ]
  }
}
```

Declarative on purpose: config is repo-committed, so a rule that could name code to run
would mean cloning a repository executes it. See [SECURITY.md](./.github/SECURITY.md).

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

## Status and limits

**Alpha.** The engine, CLI, Claude Code hook, MCP server, LangGraph adapter, diff/CI path
and repository audit all work and are covered by 509 tests. Read this before adopting:

- **Python only.** TypeScript and Java are designed but not built; other languages are
  reported as `skipped`, never silently passed.
- **Snapshot, property-based and heavily table-driven suites** are poorly served — counting
  assertions is not meaningful there.
- **Subject aliasing is a known false positive**: renaming `inv` to `invoice` reads as a
  lost subject. Pinned as a test so it cannot be forgotten.
- **The cost claim is unmeasured.** That the prescription costs zero model calls is a
  property of the architecture and holds. That repair loops therefore converge in fewer
  *total* calls against a real model has not been benchmarked, and is not claimed.
- No performance figure appears anywhere in this project without a runnable benchmark
  behind it.

---

## Contributing

Bug reports, false positives and missed detections are all welcome — the
[false positive](./.github/ISSUE_TEMPLATE/false_positive.yml) and
[missed detection](./.github/ISSUE_TEMPLATE/missed_detection.yml) templates ask for exactly
what the rules are tuned against.

```sh
python -m unittest discover -s tests -t . -q    # no dependencies required
./scripts/release-check.sh                      # full pre-flight
```

Start with [CONTRIBUTING.md](./CONTRIBUTING.md) and [RULES.md](./RULES.md).

## Documentation

| Document | Contents |
|---|---|
| [PLAN_AND_POSITIONING.md](./PLAN_AND_POSITIONING.md) | Why this exists, who it is for, what was deliberately cut |
| [IMPLEMENTATION_STAGES.md](./IMPLEMENTATION_STAGES.md) | Build order, every stage and its gate |
| [RULES.md](./RULES.md) | Engineering standards for this codebase |
| [CONTRIBUTING.md](./CONTRIBUTING.md) | How to work on it |
| [RELEASING.md](./RELEASING.md) | How a release is cut |
| [CHANGELOG.md](./CHANGELOG.md) | Release history |
| [SECURITY.md](./.github/SECURITY.md) | Threat model and reporting |

## License

[Apache-2.0](./LICENSE)
