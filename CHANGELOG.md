# Changelog

All notable changes to this project are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The serialised verdict carries its own `schema_version`, versioned independently of the
package: it is the cross-language API, and a change to its shape is breaking even when the
package version is not.

## [Unreleased]

## [0.1.6] — 2026-09-23

### Added

- **GitHub Action and Marketplace integration.** Ready-to-use composite GitHub
  Action (`action.yml`) with automated PR diff checking, SARIF code scanning annotations,
  and Job Summary reporting.
- **The per-edit gate can no longer deny the same thing forever.** After
  `loop_breaker.max_repeats_without_progress` identical denials — same session, same
  file, same rules — it stands down, says so, and leaves the finding to the stop gate.
  The finding is not waived and the message says it plainly. A capable agent used to
  escape a repeated denial by batching edits through a shell, where this gate sees
  nothing at all; a weaker one simply stopped making progress. The worst case is now
  bounded by construction rather than by how clever the agent is.

### Fixed

- **The stop gate now honours `structure.gates`, as the per-edit gate and `review`
  already did.** A change could be waved through on every edit and then refused at the
  door. Worse, `change_too_large` — whose only remedy is a commit the agent is usually
  not permitted to make — could hold a session open with nothing the agent could
  legally do to satisfy it. Shape findings are reported there and no longer blocking.
- **A weakening finding is judged against the last commit, not the last keystroke.**
  The per-edit gate compares an edit to the file on disk, which is what the previous
  edit left. That answers "did this edit weaken the suite" and not "was there anything
  here to weaken" — so an assertion written and reshaped minutes later, inside one
  uncommitted session, was reported as lost coverage. An assertion absent from the
  committed file is now treated as the draft it is. Deliberately narrow: a file with
  no committed version is **not** exempt, because writing a strong test, watching it
  fail and then weakening it is precisely the tampering this rule exists to catch.
- `verify.states_in` and `worktree.at_head` expose reconstruction and committed-content
  lookup that were previously private, rather than having callers duplicate them.


## [0.1.5] — 2026-09-23

### Added

- **Provider-neutral routing contracts.** Versioned routing profiles, sticky task
  sessions, explicit capability-checked handoffs, and bounded transfer capsules are
  available through the Python API, CLI, MCP server, LangGraph adapter, Node package,
  and Java package. Hosts retain model selection, credentials, and provider calls.
- **Release-aware SDK routing.** Node and Maven release paths now require the shared
  package-consumer and release-preflight checks in their routing profile; common JSON
  fixtures keep Python, Node, and Java transport validation aligned.
- **Optional Jev examples.** Python, Node, and Java examples show a safe, opt-in router
  boundary with deterministic fallback; no provider request occurs by default.
- **Local routing observability.** `yieldpoint routing-stats` summarizes a separate,
  redacted local ledger. It records only counts, tier, selection source, switch count,
  capsule size, and handoff outcome — never model names, prompts, diffs, provider
  payloads, or credentials.
- **Safe model routing guide.** The generated documentation site now covers observe-only
  rollout, MCP/SDK hooks, bounded handoffs, examples, and the local telemetry contract.
- **The handoff gate enforces the contract it publishes.** Every bound — switch budget,
  live checkpoint events, overhead ceiling, unverified policy — now travels in the
  profile's `handoff` block, so Python, Node, and Java apply the same numbers instead of
  each carrying their own copy of the rules. A handoff is refused after a `pass` (the
  work verified), after a `block` (a person decides), and on an `unverified` change
  unless `routing_session.allow_unverified` is set: escalating on absent evidence spends
  a larger model to answer a question nobody asked it. Each refusal names the bound it
  failed.
- **Routing reads the verdict.** `assess-routing --verdict/--repair-attempt/--loop-tripped`,
  the `yieldpoint_routing_profile` MCP tool, and the LangGraph admission node now carry
  verification state into the profile; admission placed after a verify node needs no
  further wiring. `handoff-check --overhead` and the matching MCP field supply the
  router-overhead estimate the budget is checked against.
- **`routing_session` configuration is live.** `enabled`, `checkpoint_events`,
  `router_overhead_fraction`, `allow_unverified`, and the new `required_checks` are read
  by the code that enforces them. With `enabled` false — the default — `assess` returns
  exactly what it returned before routing existed.
- **Profiles are tamper-evident.** `profile_id` is recomputed whenever the Python engine
  reads a profile back, so one edited to widen its own budget is refused by the CLI and
  MCP tools. Shared fixtures are generated by `scripts/build_routing_fixtures.py` and
  carry real digests; the set now covers valid, unverified, blocked, exhausted-budget,
  trimmed-capsule, and malformed payloads, exercised by all three languages.

- **A routing profile describes the whole task.** `build_profile` accepts a change set,
  and `assess-routing --diff` profiles one: the riskiest file decides the tier, every
  file's requirements accumulate, one file the engine cannot read makes the whole set
  inexact, and the change-budget pace is measured against the real file count. Passing a
  single `Change` is byte-identical to before, so existing hosts and the shared fixture
  digests are unaffected. `verify.states_in` exposes the diff reconstruction that
  `verify_diff` already performed, rather than duplicating it.

### Fixed

- **An unanalysable file inside an SDK no longer loses its context requirement.** The
  decision-table rows accumulate rather than replace, so such a change reports
  `large_context` *and* `multilingual_sdk` instead of only the latter.
- **A capsule no longer exceeds the `capsule_max_chars` it declares.** The digest is
  reserved before trimming rather than appended after the size check.
- **`pace` is carried in the profile**, so change-budget pressure is visible at
  admission rather than at stop time.

## [0.1.4] — unreleased

### Added

- **TypeScript and JavaScript structural analysis.** Evaluates file length, function
  length, parameter count, nesting, cyclomatic complexity, and swallowed exceptions
  via tree-sitter.
- **Diagnostics over LSP.** Compared against the committed file.

## [0.1.3] — unreleased

### Added

- **Developer evaluation walkthrough.** The README and getting-started page now show a
  disposable-repository smoke test: establish a baseline, weaken an assertion, and see
  both `yieldpoint review` and the pre-commit gate reject it.
- **Search discovery files for the documentation site.** The docs build now publishes
  `robots.txt` and a sitemap for the public GitHub Pages URLs, along with per-page
  canonical URLs, descriptions, sharing metadata, and homepage software metadata.
- **Google Search Console verification file** at the documentation-site root, retained
  after verification so ownership remains valid.

## [0.1.2] — unreleased

### Added

- **Eleven more languages.** Test files in JavaScript, TypeScript, Java, Kotlin, Go,
  Rust, C#, Ruby, PHP, Swift and Elixir are now read, alongside Python. Go is read
  through both testify and its own stdlib idiom — `if got != want { t.Errorf(...) }`,
  where the assertion is the negation of the guard, which is how most Go tests are
  written. `scripts/language_matrix.py` generates the support table, and a test holds
  the README to it so the table cannot drift from the engine.
- **Three contract rules now reach every language.** `empty_test`, `skip_marker` and
  `vacuous_assertion` were Python-only because the integrity rules were assumed to need
  control flow. Only `disabled_assertion` actually does: an empty body, an annotation
  that switches a test off, and an assertion whose subject is a literal are each
  unambiguous without it. `scripts/check_matrix.py` reports every check against every
  language, and says `n/a` where a language has no such construct rather than claiming
  a pass.
- **`weak_new_test`** — a newly added test whose every assertion only checks existence.
  Monotonicity cannot see this: there is no earlier version to be weaker than. It is the
  shape an agent produces when asked to add a feature *with tests*. Advisory by default,
  and silent when one not-null guard sits beside a real assertion.
- **`duplicate_across_files`** — the same implementation in two files of one change.
  `duplicate_implementation` only ever compared within a single file, which is the half
  a reader can already see.
- **`yieldpoint brief`** — what is true about the files a task is about to touch: lines
  of headroom, functions already at their limit, the assertions that must not get weaker,
  and the imports the file's zone forbids. A verdict arrives after the code is written;
  this arrives before. Also an MCP tool, `yieldpoint_brief`.
- **`structure.exclude`** — paths the maintainability limits skip, as globs: a directory,
  an exact file, or an extension. Only maintainability is skipped. An excluded file is
  still checked for a weakened test contract, which no path may switch off.

### Changed

- **`max_file_lines` is off by default.** A line count is the weakest proxy here for
  one-responsibility-per-module, and it fired 403 times across Requests, Click, Rich,
  Flask, Black, Cobra and Axios. A rule that flags every well-regarded codebase gets
  switched off, taking the rules that matter with it. Set it explicitly to opt in; this
  repository still sets 300 for itself.
- **Every install route now gates commits.** `install-mcp` and `install-hook` previously
  wired nothing for git, so installing through the MCP server — the usual path for an
  agent — left commits ungated. Both now write `.git/hooks/pre-commit`; pass `--no-git`
  to opt out.

### Fixed

- **The compaction ratio counted code no critique described.** `analysed_chars` summed
  every verdict while `prescription_chars` summed only those that produced one, so the
  ratio improved the more clean code happened to be verified alongside. It now divides by
  the characters of the verdicts that actually produced a critique. On this repository
  that corrects a reported 201.9x to 128.8x.


## [0.1.1] — unreleased

### Added

- **A quick start per client**, in the README and on the documentation site. Claude Code
  gets `yp init`, the restart, and `yp doctor` to tell "installed and working" from
  "installed and never ran". Cursor, VS Code, Windsurf, Zed, Cline, Roo, Kiro, Trae,
  Gemini CLI, Amazon Q, opencode and Claude Desktop get `yp init --client X --no-hook`;
  the YAML and TOML clients get the `--show` snippet. Each says which of the three doors
  it actually gets, since only Claude Code has a pre-edit hook.
- **A section on what `yp stats` is worth**, with the savings panel and what each of the
  three figures means.
- **`tests/test_docs.py` now executes the prose**: every `yp <command>` named in the
  README or on the site must exist in the CLI. The first draft of the quick start told
  people to run `yieldpoint install-git-gate`, which has never existed — the commit gate
  is installed by `init`.

### Changed

- **Maintainability findings no longer fail a run.** `file_too_long`,
  `change_too_large` and the rest of the shape rules are reported, counted and shown in
  `scan`, but they do not set a non-zero exit code and the editor hook no longer denies
  an edit for one. A weakening still stops a commit, and a mix of the two still stops a
  commit. `structure.gates: true` restores the old behaviour.

  The reason is behavioural rather than a judgement about severity: a gate that fires on
  ordinary days gets passed `--no-verify` out of habit, and the habit does not
  distinguish "this function is long" from "this assertion is gone".

### Added

- **Documentation site** at <https://tensilestream.github.io/yieldpoint/>, generated by `scripts/build_docs.py` and
  published by `.github/workflows/pages.yml`. The rules reference is built from the
  engine: a rule the code can emit but the page does not document fails the build and
  `tests/test_docs.py`, so the published page cannot drift from the code it describes.
- **Feature request issue template**, which asks for the change an agent made that
  should have been caught before it asks for a solution, and states up front the
  commitments a proposal cannot require breaking — no network call, no model call in the
  verification path, no runtime dependency in the core.

### Added

### Changed

- **Licence: Apache-2.0 → Business Source License 1.1.** Done before the first release and
  before any fork existed, because Apache-2.0 cannot be narrowed after the fact. Free in
  production for individuals, teams of fewer than ten engineers, charities, schools and
  OSI-licensed open source projects; free without limit for evaluation and development;
  commercially licensed above that. Each release converts to Apache-2.0 four years after
  it ships, irrevocably. The free tier is conditional on not circumventing licence key or
  metering functionality — a licence term rather than a code check, because in
  source-available software a check can simply be deleted.

### Added

- **`COMMERCIAL.md`** — who pays and who does not, as one table.
- **`CLA.md`** and a `Signed-off-by` requirement on code contributions, so contributed
  code can be offered on the same commercial terms as the rest. Contributors keep their
  copyright. Bug reports, false positives and missed detections need no sign-off.
- **`NOTICE` and `TRADEMARK.md`.** The name, the mark, the PyPI name and the `yieldpoint`
  and `yp` commands are not licensed with the code, so a fork needs its own name. All four
  legal files ship in the wheel and sdist.

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

[Unreleased]: https://github.com/tensilestream/yieldpoint/compare/v0.1.6...HEAD
[0.1.6]: https://github.com/tensilestream/yieldpoint/compare/v0.1.5...v0.1.6
[0.1.5]: https://github.com/tensilestream/yieldpoint/compare/v0.1.4...v0.1.5
[0.1.4]: https://github.com/tensilestream/yieldpoint/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/tensilestream/yieldpoint/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/tensilestream/yieldpoint/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/tensilestream/yieldpoint/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/tensilestream/yieldpoint/releases/tag/v0.1.0
