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

- [Install](#install) · [Quick start](#quick-start) — two commands
- [`aegisflow review`](#aegisflow-review--the-whole-product-in-one-command) · [Editor setup (MCP)](#editor-setup-mcp)
- [LangGraph](#use-it-in-your-agents-graph) · [CI and pre-commit](#gate-ci-and-commits)
- [What it checks](#what-it-checks) · [Configuration](#configuration)
- [Routing and gating](#routing-and-gating--decisions-instead-of-round-trips) · [Fan-out and long sessions](#fan-out-and-long-running-sessions)
- [Examples](./examples/)
- [Why deterministic](#why-deterministic) · [Is it helping?](#is-it-actually-helping--aegisflow-stats)
- [How wrong is it?](#how-wrong-is-it--run-the-number-yourself)
- [Status and limits](#status-and-limits) · [Why not an existing tool?](#why-not-just-use-something-that-exists)
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

Two commands. The first sets everything up; the second tells you what you already broke.

```sh
aegisflow init         # config + MCP server + editor hook, in one go
aegisflow review       # check everything you have changed but not committed
```

`init` writes three files and backs up anything it touches:

| File | What it does |
|---|---|
| `.aegisflow.json` | The rules. Committed, so the team shares one definition. |
| `.mcp.json` | Registers the MCP server, so your agent can *ask* what a rule means. |
| `.claude/settings.json` | Registers the hook, which is the part that actually *enforces*. |

The hook starts **advisory** — it reports and never blocks. Run `aegisflow init --enforce`
once you are happy with what it reports. Restart your editor so it picks both up.

### `aegisflow review` — the whole product in one command

No arguments. It reads your uncommitted diff from git, including files you have not staged
yet, and tells you whether anything you changed weakens what the tests verify.

```console
$ aegisflow review
REPAIR  1 finding(s)

  tests/test_invoice.py:14 in test_total  [assertion_monotonicity]
    Assertion on invoice.total was weakened: eq -> non_null.
    fix: Re-assert invoice.total at eq strength, or fix the code under test so the
         original assertion passes. Restore `assert invoice.total == 42`.
```

That verdict cost zero model calls and is byte-identical on every machine.

```sh
aegisflow review --staged             # only what is staged
aegisflow review --against main       # a whole branch
aegisflow review --json               # for CI
```

### Prefer to do it a piece at a time?

```sh
aegisflow scan                        # audit the repo as it stands
aegisflow install-mcp --client cursor # MCP only, any editor
aegisflow install-hook --advisory     # the enforcing half, on its own
aegisflow check --path tests/test_invoice.py --before old.py --after new.py
git diff --cached | aegisflow check --diff -
```

Everything also runs without anything on your `PATH`:

```sh
python -m aegisflow review
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

If `aegisflow` is not on the PATH your editor sees — common with conda, virtualenvs, and
editors launched from a desktop icon rather than a shell — the installer writes
`"command": "<your python>", "args": ["-m", "aegisflow", "mcp"]` instead, which always
resolves. This matters because a client that cannot find the command reports *"server
failed to start"*, not *"not on PATH"*, and you lose an hour on the wrong problem.

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

Tools offered:

| Tool | Arguments | Use |
|---|---|---|
| **`aegis_review`** | **none** | Check everything uncommitted. The one to call after finishing a set of edits. |
| `aegis_verify_change` | path, before, after | Check one edit before writing it. |
| `aegis_verify_diff` | a unified diff | Check a change set you already have. |
| `aegis_scan` | path | Audit a repository as it stands. |
| `aegis_policy` | none | List the rules in force, before planning work. |

The server also sends MCP `instructions` at startup, so a connected agent is told when to
call these rather than having to be asked each time.

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

Exit codes, so a pipeline can tell the three outcomes apart:

| Code | Meaning |
|---|---|
| `0` | Something was checked and it was clean. |
| `1` | Findings. The change weakens the suite, breaks a boundary, or trips a rule. |
| `2` | AegisFlow itself failed — bad arguments, unreadable input. |
| `3` | **Nothing in the change could be analysed.** No result to trust, and not the same as passing. Only returned when the *whole* change was unanalysable; one Python file among twenty TypeScript ones still exits `0`. |

Code `3` is the reason the CLI can be trusted in CI at all: the alternative is exiting `0`
on a change nothing looked at, which reads as approval.

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

## Routing and gating — decisions instead of round trips

An agent loop is: a model decides, a tool runs, something judges the result, repeat. Two
of those steps ask a model questions that are not language questions, and both can be
computed instead.

```python
from aegisflow.harness import middleware, Change

mw = middleware(policy=".aegisflow.json",
                tiers={"small": "haiku", "standard": "sonnet", "capable": "opus"},
                escalate_to="human-review")

mw.model_name(Change(path, before, after))   # which model this work needs
mw.before_tool("Edit", tool_input)           # allow or deny, before it runs
```

**Before the model** — how much model does this work actually need?

| Work | Risk | Tier | Why |
|---|---|---|---|
| Reword a docstring | `trivial` | `small` | cosmetic and local |
| Add a function and an import | `low` | `standard` | a normal edit |
| Restructure a module | `moderate` | `capable` | structural change of real size |
| Edit a protected test | `critical` | `human` | a weakening hides itself here |
| Verified, mechanical, small | — | `none` | **no model call at all** |

Each row costs one parse and no round trip. Asking a model which tier something is adds a
round trip to save one, and answers differently next time.

**Before the tool** — judge the edit, not the test run. A bad edit that lands costs the
test run, the failure output, the model's reasoning about the failure, and the retry.
Refusing it up front replaces all of that with one sentence naming what to restore.
[`examples/harness_middleware.py`](./examples/harness_middleware.py) prints both halves
with the character counts.

**What it returns** are typed decisions, not prose — `Choice`, `Score`, `Gate` — each
carrying the signals it was derived from, so a harness can log *why* it routed without
asking anything to explain itself.

**Two honest limits.** These read the *shape* of a change, never its meaning: a one-line
edit to a payments calculation measures as `trivial` and is not. So the tier is a ceiling
on cheapness — it says when the expensive model is unnecessary, never that a change is
unimportant. And a question it cannot answer returns `unknown` rather than a plausible
default, so a harness can fall back to a model instead of acting on a guess.

Also available in-session as the `aegis_assess` MCP tool.

---

## Fan-out and long-running sessions

A verifier for people building agents has to survive how agents are actually run: many
workers on one repository, for hours.

```python
from aegisflow.verify import verify_change
from examples.langgraph_fanout import pooled_subjects   # 20 lines, copy it

covered = pooled_subjects(edits, policy)          # every subject in the change set
verdicts = {
    edit.agent: verify_change(edit.before, edit.after, edit.path, policy,
                              also_covered=covered)
    for edit in edits
}
```

**Verify the change set, not each worker.** Worker A moves a test into a module worker B
owns. Verified separately, A is reported as deleting an assertion and B as doing nothing —
both wrong. `also_covered` tells each verification that a subject missing *here* may be
verified *there*. [`examples/langgraph_fanout.py`](./examples/langgraph_fanout.py) shows
the same edits scored both ways.

**Label the workers.** Set `AEGISFLOW_RUN_ID` and `AEGISFLOW_AGENT` per worker and
`aegisflow stats` reports findings per agent — so "the suite got weaker" becomes "worker 47
keeps doing this".

**What holds under load**, pinned by [`tests/test_concurrency.py`](./tests/test_concurrency.py):

| | |
|---|---|
| Concurrent appends | Each event is one atomic append, capped below the POSIX atomic-write size. 12 processes × 6 rounds, zero interleaved lines. Nothing in the write path reads the file to rewrite it. |
| The per-turn total | Folded incrementally from a cached byte offset, so it reads only what is new. Flat at ~1 ms whether the ledger holds 200 events or 20,000; a full re-read would be 680 ms at 20k. |
| Stalled loops | `observe()` detects the same structural state recurring rather than counting supersteps, so a loop stops when it stops making progress rather than at an arbitrary N. |
| Verification itself | No shared state, no clock, no network. Parallel-safe because it is a pure function of its inputs. |

[`examples/long_running_session.py`](./examples/long_running_session.py) demonstrates both
failure modes over 600 verdicts.

---

## Is it actually helping? — `aegisflow stats`

Every verdict appends one line to a local file. `aegisflow stats` adds them up, and keeps
three kinds of number strictly apart — because blending them is how tools end up quoting
savings nobody can reproduce.

```console
$ aegisflow stats
MEASURED — counted from what actually ran
  verifications                  47
  reported something             12
  findings                       19
  time in verification       1.4 s   (median 26 ms per verdict)

  what it caught
    assertion_monotonicity          7
    dangling_reference              5
    complexity_too_high             4
    empty_test                      3

ARCHITECTURAL — true by construction, not measured
  model calls made by AegisFlow                   0
  prescriptions assembled, not generated         19
  characters of critique produced free        3,904
  critique is 28.4x smaller than the code it describes

ESTIMATED — arithmetic on the measured bytes above
  If an LLM-as-judge had produced the same critiques:
    model calls                                  47   (one per verdict, by construction)
    input tokens                        ~   184,000   (736,412 chars / 4)

NOT CLAIMED
  That your agent converges in fewer total model calls. That needs a
  benchmark against a real model, and it does not exist yet.
```

**Why three blocks.** *Measured* is counted from what ran. *Architectural* is true by
construction — AegisFlow makes no model calls, so an LLM-as-judge doing the same job costs
one per verdict; that is a property of how each is built, not a benchmark result.
*Estimated* is arithmetic on the measured byte counts with the assumption printed beside
it. If you only trust the first block you still get a complete picture.

**On prompt compaction.** The honest version of that claim is the ratio above: the
prescription describes the change in a fraction of the characters, so a repair round feeds
the model a targeted instruction instead of the files and the reasoning to re-derive it.
Below about 1.0 the report says the critique is *larger* than the code — which happens on
tiny changes, and is printed rather than rounded away.

**What is deliberately absent:** any claim that your agent finishes in fewer total model
calls. That needs a benchmark against a real model, it does not exist, and until it does
the number will not appear here.

```sh
aegisflow stats --json      # the same figures, tiered the same way
```

Recording is **local only** — there is no network call anywhere in this package. The file
lives in `.aegisflow/`, which ignores itself, so it never shows up in a diff. Turn it off
with `"metrics": { "enabled": false }` in `.aegisflow.json`, or `AEGISFLOW_NO_METRICS=1`.

---

## How wrong is it? — run the number yourself

The question that decides whether a checker like this is usable is its false-positive
rate, because a tool that flags legitimate refactors gets switched off within a week. So
the measurement ships with the code:

```sh
python -m tests.corpus
```

It scores a committed corpus of **19 legitimate refactors** that must stay silent and
**18 tampering patterns** that must fire. Current result:

| Split | False positives | False negatives |
|---|---|---|
| Held out — written after the checker was fixed, never used to tune it | **0 / 7** | **0 / 8** |
| Tuned — used while fixing the checker | 0 / 12 | 0 / 10 |
| All | **0 / 19** | **0 / 18** |

Only the held-out row is evidence; a perfect score on cases used for debugging proves
just that the fix landed. Both are printed so you can see the split rather than take a
blended number on trust. The corpus is also a CI gate ([`tests/test_corpus.py`](./tests/test_corpus.py)),
so the rate cannot drift quietly.

Thirty-seven hand-written cases are a floor, not a false-positive rate for your
repository. If AegisFlow flags a refactor you know is sound, that is a bug —
[file it](./.github/ISSUE_TEMPLATE/false_positive.yml) and it becomes a corpus case.

## Status and limits

**Alpha.** The engine, CLI, Claude Code hook, MCP server, LangGraph adapter, diff/CI path
and repository audit all work and are covered by 520 tests. Read this before adopting:

- **Python only.** TypeScript and Java are designed but not built. Other languages are
  never silently passed — a change nothing could analyse returns status `unverified`, not
  `pass`, and the CLI exits `3` rather than `0`. If your agent writes TypeScript, this
  will tell you honestly that it checked nothing, which is useful but is not the product
  you want yet.
- **Snapshot, property-based and heavily table-driven suites** are poorly served — counting
  assertions is not meaningful there.
- **Assertions in an imported helper are invisible.** Helpers in the same module are read
  through, including helper-calling-helper chains, so weakening one is caught. A helper
  imported from another module is not expanded and its assertions are not counted.
- **Decomposing a dict comparison into per-field assertions is deliberately allowed**, even
  though it drops the implicit "and no other keys" check. That trade and its reasoning are
  written out in [`core/decomposition.py`](./aegisflow/core/decomposition.py).
- **The cost claim is unmeasured.** That the prescription costs zero model calls is a
  property of the architecture and holds. That repair loops therefore converge in fewer
  *total* calls against a real model has not been benchmarked, and is not claimed.
- No performance figure appears anywhere in this project without a runnable benchmark
  behind it.

## "Why not just use something that exists?"

Fair question, and for two of the three things AegisFlow does the answer is *you should*.

| You already have | Does it catch an agent weakening a test? |
|---|---|
| **Coverage** | No — and it is worse than neutral. Delete an assertion and coverage is unchanged; delete a whole failing test and it goes *up*. |
| **Linters** (ruff, ESLint, Spotless) | No. `assert x == 42` and `assert x` are both clean code. Nothing in a linter reads the previous version of the file. |
| **Mutation testing** | Yes, in principle — it is the rigorous answer. It also needs minutes to hours per run, so it cannot sit on the edge between `generate` and `apply`. AegisFlow is milliseconds and no model calls; use both, at different points. |
| **Code review** | Sometimes. Not reliably, in a forty-file agent diff, on the fourth one that day. |
| **`dependency-cruiser`, import-linter, ArchUnit** | For layer boundaries — yes, and they are mature. AegisFlow ships `boundary_violation` for convenience, not as a reason to adopt it. |
| **LLM-as-judge** | Sometimes, at one extra model call per round, 5–15s of latency, and a verdict that changes between runs. You cannot gate a pipeline on a judge that flakes. |

The narrow claim: **every one of those evaluates code as it now stands.** "The agent
cheated" is a statement about what was *taken away*, and only a diff-native check can
express it. That is the whole product; everything else in this repository is support.

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
