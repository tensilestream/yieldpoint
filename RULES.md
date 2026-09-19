# Yieldpoint Engineering Standards

Standards for this codebase: what may depend on what, what may not be claimed, and
what a change has to prove before it ships.

---

## 1. File length and modularisation

1. **300-line hard limit.** No source file may exceed 300 lines of code, excluding
   docstrings and blank lines. A file approaching 250 lines must be split into cohesive
   sub-modules.
2. **No utility dumps.** `utils.py`, `helpers.py`, `misc.py` and equivalents are
   prohibited. Every module has one cohesive responsibility and a name that states it.

## 2. SOLID and DRY

- **Single Responsibility** — one capability per module: diff parsing, assertion
  extraction, glob matching, verdict routing. Never two.
- **Open/Closed** — new rule types plug in as implementations of the rule interface,
  without editing the evaluation loop.
- **Liskov Substitution** — every language analyser satisfies the same extractor
  interface, with no caller-visible special cases.
- **Interface Segregation** — each framework adapter depends only on the verdict API, never
  on core internals.
- **Dependency Inversion** — the verification core depends on abstract source and diff
  inputs, never directly on the filesystem, a VCS, or a model provider.
- **DRY** — one engine. Path normalisation, assertion ranking and policy loading exist
  exactly once, in `yieldpoint.core`, and every adapter calls into it. Two implementations
  of the same check will drift, and a verifier that drifts is worthless.

## 3. Language allocation

| Layer | Language | Why |
|---|---|---|
| Verification core (`yieldpoint/core/`) | **Python**, no runtime dependencies | LangGraph and the target persona's stack are Python-first. The core stays dependency-free so it can be embedded anywhere without version conflicts. |
| Framework adapters (`yieldpoint/langgraph/`, later `adapters/`) | **Python** | Thin translation layers over the verdict API. |
| Later surfaces (MCP server, CI action, IDE) | Python, or TS where the host demands it | Every one calls the same core. None reimplements a check. |

**On Rust:** a Rust core with `pyo3`/`napi` bindings is the correct long-term shape, for
one reason only — a single implementation serving both Python and TypeScript without two
codebases drifting apart. That is an argument about correctness, not speed. Earlier drafts
justified Rust with garbage-collection jitter and `cgo` overhead; at the input sizes this
engine sees, those arguments do not hold and should not be repeated. Rust is a rewrite to
be earned after adoption, not a prerequisite.

## 4. Determinism

Determinism is the product, so it is a hard constraint on the code:

1. **No model calls in the verification path.** Ever. A verdict that consults an LLM is not
   reproducible and cannot gate a pipeline.
2. **No wall-clock, randomness, network or environment reads** inside a check. The same
   inputs must produce byte-identical output on any machine.
3. **Ordered output.** Findings are sorted by a stable key, never by set or dict iteration
   order.

## 5. Honesty of claims

1. **No performance number without a committed, runnable benchmark.** A latency or
   percentage figure in any document, README, comment or log line must be reproducible by
   the reader. Six invented microsecond figures in an earlier draft of this repository
   were deleted for this reason.
2. **No surface may assert safety it did not verify.** A check that did not run reports
   "not evaluated." Rendering a green result for an unperformed check is the most serious
   defect this project can ship — worse than shipping nothing.
3. **Plain names for real mechanisms.** A rolling window of structural hashes is called
   loop detection, not Lyapunov phase-space convergence. Vocabulary that inflates a simple
   mechanism reads as obfuscation and costs credibility with the exact reader we need.

## 6. Testing

1. Every check ships with fixtures for both directions: the pattern it must catch, and the
   legitimate code it must not flag.
2. The false-positive rate is measured on real refactors before any rule is permitted to
   return `block`.
3. Tests assert on verdicts and finding locations, never on formatted human-readable text.
