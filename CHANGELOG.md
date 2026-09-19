# Changelog

All notable changes to this project are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The serialised verdict carries its own `schema_version`, versioned independently of the
package: it is the cross-language API, and a change to its shape is breaking even when the
package version is not.

## [Unreleased]

### Added

- **`yieldpoint export`** — the ledger as JSON Lines on stdout, with per-event and
  cumulative savings on every row. `--since`, `--run` and `--agent` select a window.
- **`YIELDPOINT_SINK`** — a command, as a JSON array of argv, that each turn's new events
  are piped to. Yieldpoint spawns it and writes to its stdin; it never opens a socket, so
  the no-network guarantee is unchanged. A watermark beside the ledger sends each event
  once and does not advance when the command fails. Read from the environment and never
  from `.yieldpoint.json`: that file is committed, and SECURITY.md requires that
  configuration can never name an executable. A `metrics.sink` key there is ignored and
  reported as a policy warning.
- **`yieldpoint stats --html [PATH]`** — write the HTML report instead of printing,
  through the same renderer `yieldpoint report` uses so the two cannot drift.
- **`metrics.price_per_million`** and `stats --price` — a cost estimate from a rate you
  state, printed back beside the result. No default rate: a baked-in vendor price would
  be stale and unreproducible, which RULES.md section 5 forbids.
- **Repeat disclosure** on the savings panel and the HTML page: how many distinct file
  sets the total covers, and how many verifications re-analysed one already counted. The
  totals still count every verdict — a judge would have read every one — but a large
  number reads as distinct work, and usually is not.
- **Per-turn timeline** in `yieldpoint stats` and in the HTML report, by default. Date,
  time and savings for each verdict, with the running total after it. Calls and tokens
  stay in their existing tiers — architectural and estimated — and are never blended.

### Fixed

- **Ledger appends were lost under concurrent writers on Windows.** Append there is
  seek-to-end then write, so two processes resolved the same offset and one overwrote the
  other. No error was raised, which is why retrying could not fix it and why CI looked
  flaky. Appends now take a real cross-process lock (`fcntl.flock` / `msvcrt.locking`) on
  a sidecar file. `tests/test_concurrency.py` asserts mutual exclusion directly, on every
  platform.
- **The running total was never printed** by the human reporter: the call sat after a
  `return` and referenced a name that was not in scope.
- **`console.__all__` named `allow_notice`**, which the module does not define, so
  `from yieldpoint.console import *` raised.

Verdict `schema_version` **2**. Breaking for consumers that switch on `status`.

### Added

- **`Status.UNVERIFIED`** — a change that no rule could analyse is no longer reported as
  `pass`. Returned only when the *whole* change was unanalysable; a change with one
  analysed file among many unsupported ones stays `pass` with the gap recorded in
  `skipped`. `bool(verdict)` is `False` for it.
- **Exit code `3`** from `yieldpoint check`, distinct from `1` (findings) and `0` (clean),
  so CI can tell "I found a problem" from "I could not look".
- **`on_unverified`** on `make_router`, defaulting to its own unmapped `"unverified"`
  edge: a graph that never considered the case raises rather than quietly applying an
  unchecked change.
- **Assertions reached through a called helper** are attributed to the calling test, with
  call-site arguments substituted for the helper's parameters and helper-calling-helper
  chains followed to a bounded depth. Closes a false negative in which weakening a shared
  assertion helper was reported as nothing.
- **`python -m tests.corpus`** — a committed corpus of 19 legitimate refactors and 18
  tampering patterns, scored and split by provenance, enforced in CI by
  `tests/test_corpus.py`. A rule may not block until its false-positive rate on that
  corpus is measured.

- **`yieldpoint init`** — one command that writes `.yieldpoint.json`, registers the MCP
  server and installs the hook. Advisory by default; `--enforce` to block, `--no-hook` for
  MCP only. Idempotent, and backs up anything it touches.
- **`yieldpoint review`** — verify uncommitted work with no arguments, reading the diff
  from git. `--staged`, `--against <ref>` and `--json` for the other shapes. Exposed over
  MCP as **`yieldpoint_review`**, the zero-argument tool an agent can call after finishing a
  set of edits.
- **`python -m yieldpoint`** — the full CLI without needing anything on PATH.
- **`yieldpoint stats`** and the **`yieldpoint_stats`** MCP tool — local accounting of what
  Yieldpoint caught and what the critique cost. Figures are reported in three blocks that
  are never blended: *measured* (counted from what ran), *architectural* (true by
  construction — zero model calls made, so an LLM-as-judge costs one per verdict), and
  *estimated* (arithmetic on measured bytes, with the characters-per-token assumption
  printed beside the result). A "fewer total model calls to convergence" figure is
  deliberately absent and named as unclaimed: it has not been benchmarked.
- **`metrics` policy section.** Recording is on by default and entirely local — there is
  no network call in this package. Disabled with `"metrics": {"enabled": false}` or
  `YIELDPOINT_NO_METRICS=1`. The ledger directory writes its own `.gitignore`, so it never
  appears in a diff and Yieldpoint never edits a file the project owns.

**Fan-out and long-running sessions**

- **Per-agent attribution.** `YIELDPOINT_RUN_ID` and `YIELDPOINT_AGENT` label each worker,
  and `yieldpoint stats` reports findings per agent and distinct runs. With a fan-out of
  three hundred, "the suite got weaker" is not actionable; "worker 47 keeps doing this" is.
- **Acknowledgements in source.** `# yieldpoint: allow <rule> - <reason>` answers a finding
  the author meant. It names one rule, requires a reason, and is counted on the verdict and
  in `yieldpoint stats`, so suppression stays visible instead of quietly accumulating.
  Verdict `schema_version` **3**.
- **Ten integration examples** under `examples/`, covering LangGraph (single and fan-out),
  CrewAI, the OpenAI Agents SDK, the Claude Agent SDK, pytest, GitHub Actions, GitLab CI,
  an eval harness, and no framework at all. Exercised by `tests/test_examples.py`, because
  documentation that no longer runs is a confident wrong answer.

- **`yieldpoint stats --since / --run / --agent`.** The ledger is append-only and has no
  concept of a session; a session is a window of time, so that is what these select.
  `--since session` covers the last eight hours, and `today`, `2h`, `30m`, `7d`, `1w` all
  work. A period that cannot be read is an error rather than a silent widening, and an
  event recorded before timestamps existed is excluded from a period rather than assumed
  recent.
- **`doctor` reports whether the hook has actually fired.** Installed is not the same as
  running: a hook added mid-session does nothing until the next one, and the symptom is
  identical to it working. This is the only check that tells those apart.

### Fixed

- **Worker attribution was silently wrong.** A field inserted above `run` in `Who` rebound
  every label by one column, because `identity()` is splatted into it positionally.
  Nothing raised and no verdict looked wrong — the attribution was simply false. Field
  order is now pinned by a test.
- **The per-turn total was O(events) per read, and therefore O(events²) over a session.**
  Invisible at twenty events, 680 ms per verdict at twenty thousand. Folded incrementally
  from a cached byte offset; flat at ~1 ms regardless of ledger size. The cache is
  distrusted on read, so corrupt, stale or rotated-underneath costs one full read rather
  than a wrong number.
- **Ledger writes were not safe under a fan-out.** Events are now capped below the POSIX
  atomic-append size and written with a single append; rotation is an atomic rename behind
  an exclusive lock. The previous trim read the file and wrote it back, which discards
  whatever other agents appended in between.
- **`UNVERIFIED` was not exported** from `yieldpoint.langgraph`, so a graph could not map
  the edge the router returns.
- **A confirmation-token test named four words literally**, and passed only while the
  derived token happened not to be one of them.
- **MCP and hook commands are resolved rather than assumed.** A bare `yieldpoint` that is
  not on the client's PATH surfaces as "server failed to start", not as a missing install.
  The console script is registered by bare name when it resolves — `.mcp.json` is
  committed, so an absolute path would work on exactly one machine — and falls back to
  `<interpreter> -m yieldpoint`, which cannot fail to resolve.
- **A change consisting only of new files reported "nothing to check."** `git diff` omits
  untracked files, and emptiness was judged before they were added — so the most
  interesting thing an agent produces was the one case not checked.
- **The block message claimed a weakened test suite for any finding.** A `file_too_long`
  result now says it breaks a project rule, because the stronger wording was a claim the
  reader could check and find false.

False positives on four ordinary refactors, each addressed in subject resolution as a
fallback that can suppress a finding but never invent one:

- extracting shared assertions into a helper;
- converting a test to `async` (`await f()` and `f()` name the same subject);
- decomposing a dict or list comparison into per-field assertions, when every component
  the literal pinned is still asserted at equal strength;
- renaming the local variable holding the subject, for names assigned exactly once.

### Changed

- `Verdict` status is derived from findings *and* coverage, not from findings alone.
- Surface tests assert they emit `SCHEMA_VERSION`; the literal version is pinned once, in
  `tests/test_verdict.py`, so bumping it is a deliberate act.

## [0.1.0] — 2026-09-19

First release. Verdict `schema_version` 1.

### Added

**Verification core** — no runtime dependencies, no network, no model calls.

- `assertion_monotonicity`: per-subject domination over an assertion-strength lattice, so a
  downgrade is caught even when the assertion count is unchanged. Refactors that preserve
  subjects — parametrising, splitting, merging, renaming, moving between files — do not fire.
- Test-contract rules: vacuous assertions, new skip markers, emptied bodies, and assertions
  whose failure cannot propagate.
- `dangling_reference` and `export_removed`: refactor integrity, for every Python file
  rather than only tests.
- `boundary_violation`: architectural zones, with relative imports resolved against the
  file's own package.
- Maintainability limits: file and function length, parameters, nesting, complexity,
  structural duplication, catch-all module names.
- `change_too_large`: caps how much one change may add, per file and across a change set.
- Generated-code detection across ecosystems, by header marker and path convention.
- `ci_check_removed` and `ci_check_disabled`: integrity of the checks themselves — a job
  deleted, a step gated on `if: false`, `continue-on-error: true` added, or `|| true`
  appended. Lexical, so these warn and cannot block.
- Assertion styles: bare `assert`, `unittest`, assertpy/AssertJ, Jest, Chai, Hamcrest
  matchers.

**Surfaces**

- `yieldpoint check` — verify a file transition or a unified diff. Exit `0`/`1`/`2`.
- `yieldpoint scan` — audit a repository as it stands.
- Repository scaffolding: issue templates for false positives and missed detections, a
  pull-request checklist derived from RULES.md, CODEOWNERS, Dependabot, a security policy,
  and a `.pre-commit-config.yaml` that runs Yieldpoint on staged changes.
- `yieldpoint hook` / `install-hook` — Claude Code `PreToolUse` gate.
- `yieldpoint linters` — 24 curated external tools, opt-in, advisory only.
- `yieldpoint mcp` — Model Context Protocol server over stdio, no dependencies. Tools:
  `yieldpoint_verify_change`, `yieldpoint_verify_diff`, `yieldpoint_scan`, `yieldpoint_policy`.
- `yieldpoint install-mcp` — registers the server with Claude Code, Claude Desktop, Cursor,
  Windsurf, VS Code or Zed, or prints the snippet with `--show`.
- `yieldpoint.langgraph` — verification node, verdict router, semantic loop breaker.
- `yieldpoint.speech` — spoken verdicts and confirmation tokens for voice-driven agents.

### Design decisions worth knowing

- **Findings are differential.** A problem that predates a change is not attributed to it.
- **Uncertainty cannot block.** `LEXICAL`, `UNRESOLVED` and `EXTERNAL` findings are
  structurally prevented from blocking, enforced in `Finding.__post_init__`.
- **The hook fails open.** Unreadable payloads, timeouts and verifier errors allow the edit.
- **Linter config cannot name a command.** Only curated adapters may be enabled, because
  `.yieldpoint.json` is repo-committed.

### Known limits

- Python only; other languages are reported as `skipped`, never silently passed.
- Subject aliasing (`inv` renamed to `invoice`) is a false positive, pinned as a test.
- The repair-loop cost claim is not benchmarked against a real model.

[Unreleased]: https://github.com/tensilestream/yieldpoint/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/tensilestream/yieldpoint/releases/tag/v0.1.0
