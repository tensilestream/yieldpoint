# Changelog

All notable changes to this project are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The serialised verdict carries its own `schema_version`, versioned independently of the
package: it is the cross-language API, and a change to its shape is breaking even when the
package version is not.

## [Unreleased]

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
