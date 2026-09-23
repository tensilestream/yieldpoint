# Provider-neutral model routing and context-safe escalation

**Status:** Proposed implementation plan  
**Scope:** Python CLI/MCP/core, Python LangGraph, Node LangGraph.js, Java
LangGraph4j, documentation, examples, and release verification.

## Decision

Yieldpoint remains the deterministic verifier and signal producer. It will not
become a hosted model router, call an LLM, or authorize an irreversible action.

It will instead publish a versioned, provider-neutral **routing profile** from
the evidence it already computes: change scope, language coverage, structural
risk, verification requirements, verdict status, repair-loop state, and a
context-transfer budget. A host application may map that profile to its own
models, to Jev, or to another routing service.

The default policy is **sticky selection**:

1. Select a model once when work is admitted.
2. Keep it for normal work and repair attempts.
3. Permit one explicit escalation at a checkpoint; never switch per edit, tool
   call, or chat message.
4. Transfer a compact, deterministic task capsule when escalating.
5. Verify before applying or reporting completion.

This prevents the usual token-loss failure: an extra routing call and repeated
full-transcript injection costing more than the model it was intended to save.

## Non-goals and invariants

### Non-goals

- Ship a proprietary model, router endpoint, credential store, or network
  dependency.
- Treat provider confidence as correct before calibration against labelled team
  outcomes.
- Treat a routing score as authorization for deployment, destructive tools, or
  policy exceptions.
- Replace tests, CI, code review, or the canonical `yieldpoint review` verdict.
- Reimplement routing rules independently in Node and Java.

### Invariants

- Python CLI remains the canonical rule engine; SDKs call it rather than copy
  verifier rules.
- Same repository, policy, change, and verdict produce identical profile JSON.
- `unverified` is never converted to `pass` by routing.
- Provider use is opt-in. The host owns credentials, model names, privacy, and
  the final action.
- Each handoff is visible in state and telemetry, policy-bounded, and linked to
  a task-capsule digest.
- Current `risk`, `tier`, `model_for`, `pace`, verdict routers, and SDK APIs
  remain backward compatible for at least one minor release.

## Existing foundation and gaps

| Existing component | Current responsibility | Required evolution |
|---|---|---|
| `harness.routing.risk` | Deterministic structural risk | Stable cross-SDK routing contract |
| `tier` / `model_for` | Maps risk to local tiers/models | Task admission and handoff lifecycle |
| `harness.middleware` | Assessment before model/tool work | Persisted task-level selection |
| `harness.pacing.pace` | 60%/100% change-budget advice | Surface advice at proactive checkpoints |
| Python/Node/Java graph routers | Bound repair/stalled retries | Share session state beyond verdict edges |
| MCP assess/review | Advisory evidence | Machine-readable profile and lifecycle |

The supplied review material is evidence, not instructions. It motivates four
requirements: distinguish baseline debt from new debt, state unsupported
analysis plainly, surface budget pressure before stop/commit time, and make
acknowledgements/remediation actionable.

## Target architecture

```text
Task objective + repo/diff
          |
          v
Yieldpoint admission assessment
(signals, coverage, required checks)
          |
          v  RoutingProfile v1
Host-owned selection policy
(deterministic map or optional Jev)
          |
          v
Sticky task session: selected model + bounded repairs
          |
          +--> Yieldpoint verification --> pass / repair / block / unverified
          |
          +--> explicit checkpoint only --> task capsule --> stronger model/human
```

Provider-specific code stays at the application boundary. Yieldpoint emits
evidence and enforces limits; it does not receive credentials or make external
model calls.

## Contract: `RoutingProfile` v1

### Schema and source of truth

Add `yieldpoint/harness/profile.py` as the only source of profile computation.
It contains frozen dataclasses, validation, canonical JSON serialization, and
`ROUTING_PROFILE_SCHEMA_VERSION = 1`. It must not import provider SDKs.

```json
{
  "schema_version": 1,
  "profile_id": "sha256:...",
  "risk": {"value": "high", "reason": "...", "signals": {}},
  "tier": {"value": "capable", "reason": "...", "options": []},
  "coverage": {
    "analysed_paths": ["sdk/node/src/router.js"],
    "unverified_paths": [],
    "languages": ["python", "javascript"],
    "exact_analysis": true
  },
  "change": {
    "files": 3,
    "added_lines": 84,
    "deleted_lines": 12,
    "structural": true,
    "baseline_findings": 4,
    "introduced_findings": 1
  },
  "verification": {
    "status": "repair",
    "required": ["unit_tests", "package_consumer"],
    "findings": ["boundary_violation"],
    "repair_attempt": 1,
    "loop_tripped": false
  },
  "requirements": {
    "capabilities": ["tool_use", "strong_reasoning"],
    "minimum_context_window": "large",
    "suggested_policy": "sticky_capable",
    "may_skip_model": false
  },
  "handoff": {
    "max_model_switches": 1,
    "switch_allowed_now": false,
    "reason": "normal repair stays with the admitted model",
    "capsule_max_chars": 12000
  },
  "pace": {"value": "wrap-up", "signals": {"budget_used": 0.71}}
}
```

Rules for this contract:

- `profile_id` is SHA-256 of canonical JSON excluding itself, so a host can
  detect a stale profile/capsule pairing without retaining source code.
- `baseline_findings` are existing findings outside changed lines. They do not
  raise a model tier by themselves. `introduced_findings` are attributable to
  the diff and do.
- `unverified_paths` makes `exact_analysis` false. Unsupported analysis is a
  first-class signal, never a clean result.
- Allowed `required` values are `unit_tests`, `package_consumer`,
  `release_preflight`, `integration_tests`, and `human_review`.
- Capabilities are closed v1 vocabulary: `tool_use`, `strong_reasoning`,
  `large_context`, `code_generation`, `multilingual_sdk`, `human_review`.
  Provider labels are mapped outside Yieldpoint.
- The profile contains no source text, prompt text, credentials, chat history,
  or provider model ID.

### Decision table

Build requirements from existing deterministic `risk`/`tier` results, then use
an ordered data table; first applicable row wins.

| Condition | Requirement | Suggested policy | Handoff behavior |
|---|---|---|---|
| Protected test changed | `human_review` | `human_before_land` | No automatic switch |
| `block` verdict | `human_review` | `block` | No model call |
| Exact analysis unavailable | `large_context`, `strong_reasoning` | `sticky_capable` | Checkpoint only |
| Cross-SDK/release/package change | `multilingual_sdk`, `tool_use`, `strong_reasoning` | `sticky_capable` | One handoff after failure |
| High risk or failed repair | `tool_use`, `strong_reasoning` | `sticky_capable` | One handoff after distinct failure |
| Small, mechanical, verified change | none | `no_model_after_verify` | No model call |
| Everything else | `code_generation` | `sticky_standard` | No switch before verification |

Implement the table as pure data-driven functions with complete tests. Semantic
importance remains a policy concern via existing `routing.escalate_paths`.

### Configuration

Add an optional `routing_session` object to `.yieldpoint.json`:

```json
{
  "routing_session": {
    "enabled": false,
    "max_model_switches": 1,
    "capsule_max_chars": 12000,
    "router_overhead_fraction": 0.05,
    "allow_unverified": false,
    "checkpoint_events": ["verification_failed", "repair_exhausted", "loop_tripped"],
    "required_checks": {
      "cross_sdk_release": ["unit_tests", "package_consumer", "release_preflight"]
    }
  }
}
```

Defaults retain present behavior. Validate switch count `0..2`, capsule size
`1000..24000`, and overhead fraction `0..0.20`; invalid settings warn and keep
safe defaults.

## Context-safe session lifecycle

### Admission

The host gives Yieldpoint objective metadata, repository root, and a current
change/plan. Yieldpoint returns a profile. The host persists only its own
selection record:

```json
{
  "routing_session_version": 1,
  "task_id": "host-generated-opaque-id",
  "profile_id": "sha256:...",
  "selected_model": "host-owned-name",
  "selection_source": "deterministic|jev|manual",
  "switch_count": 0,
  "selection_reason": "..."
}
```

Jev may be called by the host with the profile capability requirements, its
candidate list, priorities, and privacy constraints. Do not send the whole
repository, raw transcript, secrets, or an assertion that confidence authorizes
the action.

### Normal execution and handoff

Routine edits and repair attempts use the admitted model. Existing verifier
nodes remain after generation and before apply. `pace=wrap-up` is advisory at a
natural checkpoint, not a forced interruption.

Allow a handoff only when all conditions are true:

1. Policy permits it and `switch_count < max_model_switches`.
2. A configured event occurred: failed verification, exhausted repairs,
   repeated-state loop, or explicit user request.
3. The candidate satisfies every profile capability.
4. Estimated router plus capsule input is within overhead budget, or the host
   records a user-visible override.
5. `block` and mandatory human-review policies are not bypassed.

Otherwise return the existing `escalate`/human graph edge; never silently select
another model.

### Task capsule

Add `build_task_capsule(session, profile, verdict, ...)`. It is deterministic
plain JSON with optional human rendering, containing:

- immutable objective and acceptance criteria from the host;
- repo/policy identifiers (not absolute home paths by default);
- profile ID, selection reason, changed paths, bounded diff excerpt;
- verdict, finding IDs, prescriptions, test commands/outcomes;
- completed actions, rejected approaches, repair count, loop state, and known
  unknowns/unverified paths;
- digest and host-managed artifact references.

Exclude chain-of-thought, credentials, unbounded transcripts, unrelated source,
and raw secrets. On size pressure, trim old diff excerpts, verbose test output,
then completed-action detail. Never trim objective, constraints, current
findings, unverified state, or acceptance criteria. Record `truncated` keys.

## Seven implementation stages

### Stage 1 — Contract and policy foundation

**Files:** `yieldpoint/harness/profile.py`, `yieldpoint/core/policy.py`,
`yieldpoint/harness/__init__.py`, `tests/test_routing_profile.py`,
`tests/test_policy.py`.

- Define profile/session dataclasses, canonical serializer, and validation.
- Derive fields from `Change`, `Signals`, `risk`, `tier`, `pace`, and verdict.
- Add config defaults/warnings and explicit baseline/new finding input.

**Complete when:** same inputs give byte-identical JSON; invalid policy is safe;
existing harness tests remain unchanged.

### Stage 2 — Session, capsule, and deterministic handoff gate

**Files:** `yieldpoint/harness/session.py`, `yieldpoint/harness/capsule.py`,
`yieldpoint/harness/middleware.py`, `tests/test_routing_session.py`,
`tests/test_capsule.py`.

- Implement admission, checkpoint, `can_handoff`, immutable state updates.
- Enforce switch/overhead limits without provider access.
- Build bounded/redacted capsules and event types.

**Complete when:** no repair loop exceeds configured handoffs; block/human rules
cannot auto-route; trimming retains safety-critical fields.

### Stage 3 — CLI and MCP surface

**Files:** CLI command modules, `yieldpoint/mcp/schemas.py`,
`yieldpoint/mcp/tools.py`, `yieldpoint/mcp/server.py`, CLI/MCP tests.

Add:

```sh
yieldpoint assess-routing --diff FILE --json
yieldpoint build-capsule --session SESSION.json --profile PROFILE.json --json
yieldpoint handoff-check --session SESSION.json --profile PROFILE.json --event verification_failed --json
```

Add advisory MCP tools `yieldpoint_routing_profile`,
`yieldpoint_build_task_capsule`, and `yieldpoint_handoff_check`. Keep
`yieldpoint_assess` response-compatible; add the profile only as an additive
key.

**Complete when:** JSON schemas/exit behavior are tested and every core path is
proven to make no provider call.

### Stage 4 — Python LangGraph reference integration

**Files:** `yieldpoint/langgraph/session.py`, `node.py`, `router.py`,
`examples/langgraph_model_routing.py`, LangGraph tests.

- Add optional admission/checkpoint nodes with JSON-compatible state.
- Preserve `make_router`; introduce separate `make_handoff_router`.
- Provide a host callback that maps requirements to models, without a Jev
  dependency.

**Complete when:** saved/reloaded state chooses the same route, normal repair
does not switch, and configured failed verification can switch once.

### Stage 5 — Node and Java parity via shared fixtures

**Files:** `sdk/node/src/profile.js`, `sdk/node/src/session.js`, Java
`RoutingProfile`/`RoutingSession`, `fixtures/routing-profile/`, SDK tests.

- Consume canonical CLI JSON; do not recalculate Python rules.
- Validate and transport profile/session/capsule state, including `canHandoff`.
- Share fixtures for valid, unverified, blocked, exhausted-budget, trimmed, and
  malformed payloads.

**Complete when:** Python, Node, and Java agree on all fixtures and each runs a
real isolated package-consumer example.

### Stage 6 — Optional Jev adapter and examples

**Files:** Python/Node/Java Jev examples and SDK/integration docs.

- Map profile requirements to a host-maintained candidate list.
- Treat returned selection/confidence as input to `handoff-check`, not authority.
- Fall back deterministically when Jev is unavailable, low-confidence,
  malformed, over-budget, or has no capable candidate.
- Include calibration-file and offline-replay examples; no global hard-coded
  confidence threshold.

**Complete when:** examples run with a fake local router; real credentials are
explicit environment opt-in; no provider dependency is mandatory.

### Stage 7 — Observability, docs, rollout, release

**Files:** metrics/report modules, `docs/`, `README.md`, `CHANGELOG.md`, CI and
release scripts.

- Record redacted local events: profile digest/tier, selection source,
  handoff outcome, capsule size, estimated overhead, verdict/final result.
- Extend report with routing totals and clearly label token estimates.
- Release API docs, provider-neutral guide, Jev example, Python/Node/Java/MCP/
  hook examples.
- Roll out observe-only, then shadow selection, then opt-in handoff enforcement;
  never default to provider routing.

**Complete when:** docs and release preflight pass, all SDK consumers pass, and
`routing_session.enabled: false` fully rolls back to current behavior.

## Test matrix

| Layer | Required coverage |
|---|---|
| Profile rules | Ordered rules, determinism, unsupported language, baseline debt, malformed input |
| Policy | Defaults, bounds, absent-config compatibility |
| Session | Admission, no per-tool switch, one allowed/second denied, restart/reload |
| Capsule | Retained critical content, truncation, redaction, deterministic digests |
| CLI/MCP | Schemas, exit codes, additive compatibility, no-network core path |
| Graph/SDK | Python/Node/Java state round trip and explicit `unverified` route |
| End to end | Normal repair no switch; failed repair one switch; second failure human; release checks required |
| Performance | Profile p95 within current local assessment budget; capsule never reads entire repo |

Add negative tests specifically for routing every edit, unbounded transcript
capsules, switching after a pass, and accepting a provider candidate without all
required capabilities.

## Measurement and launch gates

Measure the whole task, not a provider's per-call price:

- total model input/output tokens including routing and summary calls;
- model/tool retries, switches, and human escalations;
- first-pass and final verification rate; time to verified completion;
- false-safe/false-escalation rates on labelled outcomes;
- routing-overhead-budget breaches, capsule sizes, and missing-context incidents;
- human overrides of routing decisions.

Pilot gates:

1. No regression in verified completion versus sticky-capable baseline.
2. Median total tokens do not rise; p95 rises only with documented quality gain.
3. Zero silent `unverified` to `pass` transitions.
4. Every provider-driven handoff passes deterministic `handoff-check`.
5. Confidence thresholds are calibrated on held-out labelled tasks before
   automated production selection.

## Documentation, security, and rollback

Deliver `docs/routing.html`, additions to integrations/SDK/CLI docs, README
overview, and runnable Python/Node/Java examples. Each provider example must
show deterministic fallback, candidate filtering, confidence as a signal,
capsule construction, one-handoff limit, and final Yieldpoint verification.

All fields are additive. Local sessions default to digest-only telemetry; raw
diffs must not be logged. Persisted session artifacts belong in `.gitignore`.
Provider calls require explicit environment opt-in and a redaction hook.

Implementation order is Stage 1 through Stage 7. Every pull request includes
updated fixtures where applicable, cross-language tests, no-network core tests,
documentation, and `./scripts/release-check.sh`. A stage is complete only when
its stated acceptance checks pass, not merely when its code compiles.
