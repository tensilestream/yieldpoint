# Changelog

All notable changes to this project are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The serialised verdict carries its own `schema_version`, versioned independently of the
package: it is the cross-language API, and a change to its shape is breaking even when the
package version is not.

## [Unreleased]

Verdict `schema_version` **2**. Breaking for consumers that switch on `status`.

### Added

- **`Status.UNVERIFIED`** — a change that no rule could analyse is no longer reported as
  `pass`. Returned only when the *whole* change was unanalysable; a change with one
  analysed file among many unsupported ones stays `pass` with the gap recorded in
  `skipped`. `bool(verdict)` is `False` for it.
- **Exit code `3`** from `aegisflow check`, distinct from `1` (findings) and `0` (clean),
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
  `tests/test_corpus.py`. This is the measured false-positive rate that
  PLAN_AND_POSITIONING.md §7 requires before any rule may block.

- **`aegisflow init`** — one command that writes `.aegisflow.json`, registers the MCP
  server and installs the hook. Advisory by default; `--enforce` to block, `--no-hook` for
  MCP only. Idempotent, and backs up anything it touches.
- **`aegisflow review`** — verify uncommitted work with no arguments, reading the diff
  from git. `--staged`, `--against <ref>` and `--json` for the other shapes. Exposed over
  MCP as **`aegis_review`**, the zero-argument tool an agent can call after finishing a
  set of edits.
- **`python -m aegisflow`** — the full CLI without needing anything on PATH.
- **`aegisflow stats`** and the **`aegis_stats`** MCP tool — local accounting of what
  AegisFlow caught and what the critique cost. Figures are reported in three blocks that
  are never blended: *measured* (counted from what ran), *architectural* (true by
  construction — zero model calls made, so an LLM-as-judge costs one per verdict), and
  *estimated* (arithmetic on measured bytes, with the characters-per-token assumption
  printed beside the result). A "fewer total model calls to convergence" figure is
  deliberately absent and named as unclaimed, per PLAN_AND_POSITIONING.md §4.1.
- **`metrics` policy section.** Recording is on by default and entirely local — there is
  no network call in this package. Disabled with `"metrics": {"enabled": false}` or
  `AEGISFLOW_NO_METRICS=1`. The ledger directory writes its own `.gitignore`, so it never
  appears in a diff and AegisFlow never edits a file the project owns.

**Fan-out and long-running sessions**

- **Per-agent attribution.** `AEGISFLOW_RUN_ID` and `AEGISFLOW_AGENT` label each worker,
  and `aegisflow stats` reports findings per agent and distinct runs. With a fan-out of
  three hundred, "the suite got weaker" is not actionable; "worker 47 keeps doing this" is.
- **Acknowledgements in source.** `# aegisflow: allow <rule> - <reason>` answers a finding
  the author meant. It names one rule, requires a reason, and is counted on the verdict and
  in `aegisflow stats`, so suppression stays visible instead of quietly accumulating.
  Verdict `schema_version` **3**.
- **Ten integration examples** under `examples/`, covering LangGraph (single and fan-out),
  CrewAI, the OpenAI Agents SDK, the Claude Agent SDK, pytest, GitHub Actions, GitLab CI,
  an eval harness, and no framework at all. Exercised by `tests/test_examples.py`, because
  documentation that no longer runs is a confident wrong answer.

- **`aegisflow stats --since / --run / --agent`.** The ledger is append-only and has no
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
- **`UNVERIFIED` was not exported** from `aegisflow.langgraph`, so a graph could not map
  the edge the router returns.
- **A confirmation-token test named four words literally**, and passed only while the
  derived token happened not to be one of them.
- **MCP and hook commands are resolved rather than assumed.** A bare `aegisflow` that is
  not on the client's PATH surfaces as "server failed to start", not as a missing install.
  The console script is registered by bare name when it resolves — `.mcp.json` is
  committed, so an absolute path would work on exactly one machine — and falls back to
  `<interpreter> -m aegisflow`, which cannot fail to resolve.
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

- `aegisflow check` — verify a file transition or a unified diff. Exit `0`/`1`/`2`.
- `aegisflow scan` — audit a repository as it stands.
- Repository scaffolding: issue templates for false positives and missed detections, a
  pull-request checklist derived from RULES.md, CODEOWNERS, Dependabot, a security policy,
  and a `.pre-commit-config.yaml` that runs AegisFlow on staged changes.
- `aegisflow hook` / `install-hook` — Claude Code `PreToolUse` gate.
- `aegisflow linters` — 24 curated external tools, opt-in, advisory only.
- `aegisflow mcp` — Model Context Protocol server over stdio, no dependencies. Tools:
  `aegis_verify_change`, `aegis_verify_diff`, `aegis_scan`, `aegis_policy`.
- `aegisflow install-mcp` — registers the server with Claude Code, Claude Desktop, Cursor,
  Windsurf, VS Code or Zed, or prints the snippet with `--show`.
- `aegisflow.langgraph` — verification node, verdict router, semantic loop breaker.
- `aegisflow.speech` — spoken verdicts and confirmation tokens for voice-driven agents.

### Design decisions worth knowing

- **Findings are differential.** A problem that predates a change is not attributed to it.
- **Uncertainty cannot block.** `LEXICAL`, `UNRESOLVED` and `EXTERNAL` findings are
  structurally prevented from blocking, enforced in `Finding.__post_init__`.
- **The hook fails open.** Unreadable payloads, timeouts and verifier errors allow the edit.
- **Linter config cannot name a command.** Only curated adapters may be enabled, because
  `.aegisflow.json` is repo-committed.

### Known limits

- Python only; other languages are reported as `skipped`, never silently passed.
- Subject aliasing (`inv` renamed to `invoice`) is a false positive, pinned as a test.
- The repair-loop cost claim is not benchmarked against a real model.

[Unreleased]: https://github.com/tensilestream/AgeisFlow/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/tensilestream/AgeisFlow/releases/tag/v0.1.0
