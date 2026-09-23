# Remediation plan — provider-neutral routing

**Status:** Proposed, following a review of commits `fb7cd7f..9018c94` against
`implementation-plan-provider-neutral-routing.md`.
**Verified against:** working tree at `9018c94`; `python3 -m unittest discover -s tests -t .`
reports 1326 tests, OK.

## Verdict on the original plan

The plan itself is sound. Its decision, non-goals, invariants, staging, and test
matrix are internally consistent and do not need rewriting. The architecture that
shipped matches its shape: a pure `harness/profile.py`, a pure `harness/session.py`,
a bounded `harness/capsule.py`, policy bounds in `core/routingsession.py`, three CLI
commands, three MCP tools, LangGraph admission/handoff nodes, Node and Java transport,
shared fixtures, a redacted `routingledger`, docs, and Jev examples with deterministic
fallback. No provider SDK is imported by any core path, and no core path makes a
network call.

What did not ship is **enforcement**. Several of the plan's stated invariants are
represented in the data model but not actually applied at runtime, and several
configuration fields are parsed, validated, warned about — and then never read. The
result is a contract that describes more safety than it enforces. Everything below is
a change to the *implementation*, not to the plan.

---

## Findings

### Severity 1 — invariants stated but not enforced

**1.1 The verdict never reaches the profile in any shipped entry point.**
`verification.status` is always `"unverified"` in practice. No caller passes
`ProfileContext(verdict=...)`:

- `yieldpoint/routingcmd.py:59` — `build_profile(change, policy)`
- `yieldpoint/mcp/tools.py:148` — same
- `yieldpoint/langgraph/session.py:25` — same
- `yieldpoint/harness/middleware.py:177` — `ProfileContext(signals=found)` only

Consequence: two of the seven decision-table rows — `block` verdict → `human_review`,
and failed repair → `sticky_capable` — are unreachable outside a direct library call.
The plan's "`block` verdict / no model call" row is, today, dead code everywhere a
user can actually reach it.

**1.2 A handoff is permitted after a passing verdict.**
`can_handoff` never inspects `verification.status`. Verified:

```
status: pass | handoff after pass: (True, 'explicit checkpoint permits one model handoff')
```

The plan lists "switching after a pass" as a required negative test. It is neither
tested nor prevented.

**1.3 The overhead budget is not enforced.**
`yieldpoint/harness/session.py:110` hardcodes `0 <= fraction <= 0.20` instead of
reading `policy.routing_session.router_overhead_fraction` (default `0.05`). Verified:
`estimated_overhead_fraction=0.19` is allowed under default policy. Worse, no entry
point supplies a non-zero value at all — the CLI has no `--overhead` flag, the MCP
schema has no field, and the LangGraph router does not set one. `docs/routing.html`
nevertheless tells the reader a handoff is allowed "only within the switch and
overhead budgets". The documentation currently asserts a guarantee the code does not
provide.

**1.4 `routing_session.checkpoint_events` is dead configuration.**
The policy reader validates it and warns on unknown events
(`core/policyfields.py:118-122`), but `can_handoff` gates on the module-level
`CHECKPOINTS` constant (`harness/session.py:12`). Setting
`"checkpoint_events": ["loop_tripped"]` still permits `verification_failed`.

**1.5 `routing_session.enabled` and `allow_unverified` are dead configuration.**
Neither is read anywhere outside the policy reader and its test. In particular
`middleware.assess` always builds and attaches `routing_profile` regardless of
`enabled`, so Stage 7's acceptance check — "`routing_session.enabled: false` fully
rolls back to current behavior" — is not met by the default configuration.

**1.6 Decision-table rows 3 and 4 are inverted.**
`_requirements` (`harness/profile.py:118-131`) tests the release path *before*
`signals.analysable`. The plan orders "exact analysis unavailable" above "cross-SDK /
release". Verified for `sdk/node/src/router.js`:

```
capabilities: ['multilingual_sdk', 'strong_reasoning', 'tool_use']
exact_analysis: False
minimum_context_window: standard
```

A file Yieldpoint cannot analyse, inside an SDK, loses `large_context` and reports a
`standard` context window. This directly contradicts "Unsupported analysis is a
first-class signal, never a clean result."

### Severity 2 — contract fields that are structurally inert

**2.1 `repair_attempt` and `loop_tripped` are hardcoded `0` / `False`**
(`harness/profile.py:97`). `ProfileContext` has no fields for them, so the LangGraph
`ATTEMPTS_KEY` / `TRIPPED_KEY` state that already exists cannot reach the profile.
The `repair_exhausted` and `loop_tripped` checkpoints therefore have no evidence
behind them in the profile a host reads.

**2.2 The `pace` block is missing from the profile entirely.**
The plan's schema includes `"pace": {"value": ..., "signals": {...}}` and Stage 1 says
to derive from `pace`. `harness/pacing.pace` exists and is not called by `profile.py`.
Stage 7's "surface budget pressure before stop/commit time" requirement has no carrier.

**2.3 `required_checks` is absent from the policy.**
The plan's config block includes `required_checks: {"cross_sdk_release": [...]}`. It
is not a field on `core/routingsession.RoutingSession` and is not read by
`_routing_session`, so it is silently discarded. `verification.required` is hardcoded
inside `_requirements`.

**2.4 `profile_id` integrity is never checked.**
`validate_profile` (and the Node and Java equivalents) accept any non-empty string.
Nothing recomputes the digest, so the plan's stated purpose — "a host can detect a
stale profile/capsule pairing" — is unenforced. `fixtures/routing-profile/valid-profile.json`
uses the placeholder `"sha256:fixture-valid"`, so no test in any language proves the
digest is reproducible.

**2.5 `change.files` is permanently `1`.**
`harness/signals.Change` is single-file, so `assess-routing` takes
`--path/--before/--after` rather than the plan's `--diff FILE`, and a multi-file change
set cannot be profiled. The shipped surface is narrower than the documented one.

### Severity 3 — cross-language parity

**3.1 Node and Java reimplement the handoff gate.**
`sdk/node/src/session.js:canHandoff` and
`sdk/java/.../RoutingSession.canHandoff` each re-derive the rules the plan's non-goals
explicitly forbid duplicating ("Reimplement routing rules independently in Node and
Java"). They have already drifted: Python checks the overhead fraction; neither of the
other two does. This is precisely the failure the invariant was written to prevent.

**3.2 The shared fixture set is incomplete.**
Stage 5 requires fixtures for valid, unverified, blocked, exhausted-budget, trimmed,
and malformed payloads. Present: `valid-profile`, `valid-session`, `unverified-profile`,
`invalid-profile`. Missing: blocked, exhausted-budget, trimmed. `unverified-profile.json`
is referenced by no test in Python, Node, or Java — it is a dead fixture.

**3.3 No capsule transport in Node or Java.** Stage 5 lists "profile/session/capsule
state"; only profile and session shipped.

### Severity 4 — defects and surface deviations

- **4.1** `harness/capsule.py:_bound` computes the digest *after* the size check and
  then inserts it, so the final capsule exceeds `capsule_max_chars`. Verified: a
  1000-char cap yields a 1032-char capsule.
- **4.2** Dead branch at `harness/session.py:100`:
  `if request.event != "user_requested" and request.event not in CHECKPOINTS` is
  unreachable — the first guard already rejected every event outside `CHECKPOINTS`.
- **4.3** `_language` (`profile.py:138`) maps only `py`, `js`, `ts`, `java`.
  `coverage.languages` is `["unknown"]` for Go, Rust, Kotlin, C#, and always a
  single-element list even though the field is plural.
- **4.4** `middleware.assess` computes `risk` and `tier`, then `build_profile`
  computes both again from the same signals — duplicated work on the hot assessment
  path the plan asks to keep within its current budget.
- **4.5** Stage 7 says "extend report with routing totals"; instead a separate
  `routing-stats` command shipped and `yieldpoint/report.py` has no routing content.
- **4.6** The Jev examples (`examples/jev_router.py`, `examples/node/jev_router.mjs`,
  `examples/java/JevRouter.java`) stop at `admit`. Stage 6 requires the returned
  selection and confidence be fed into `handoff-check`, "not authority". No example
  demonstrates that.
- **4.7** Required negative tests from the plan are absent: switching after a pass,
  routing every edit, unbounded transcript capsule, and (in Python) accepting a
  candidate without all required capabilities.
- **4.8** Persisted routing artifacts are not in `.gitignore`, which the plan
  requires. Note `.yieldpoint/metrics.jsonl` is likewise absent, so this matches
  existing repository practice rather than regressing it.
- **4.9** `plan/implementation-plan-provider-neutral-routing.md` is committed to the
  public tree. This conflicts with the standing preference to keep planning documents
  out of the launch tree.

---

## Remediation stages

Ordered so that each stage leaves the tree green and shippable. Stages R1 and R2
are required before this feature can honestly be described as enforcing the plan.

### R1 — Make the gate enforce what the contract claims

**Files:** `yieldpoint/harness/session.py`, `yieldpoint/harness/profile.py`,
`yieldpoint/core/routingsession.py`, `yieldpoint/core/policyfields.py`,
`tests/test_routing_profile.py`.

1. Give `can_handoff` access to the session policy. Add an explicit
   `RoutingSessionPolicy` argument (or carry the resolved bounds into the profile's
   `handoff` block — preferred, since the profile is already the transport the other
   languages read). Carry `checkpoint_events`, `router_overhead_fraction`, and
   `allow_unverified` into `handoff` so Node and Java inherit them for free.
2. Gate on the configured `checkpoint_events`, not the module constant. Keep
   `CHECKPOINTS` as the validation vocabulary only.
3. Compare `estimated_overhead_fraction` against the configured fraction.
4. Refuse a handoff when `verification.status == "pass"`, and when it is
   `"unverified"` unless `allow_unverified` is set.
5. Delete the unreachable branch at `session.py:100`.
6. Reorder `_requirements` so `not signals.analysable` is tested before
   `_is_release_path`, and union the capabilities when both apply — an unanalysable
   SDK file needs `large_context` *and* `multilingual_sdk`.

**Complete when:** an unanalysable SDK path reports `large_context` and
`minimum_context_window: "large"`; a `pass` profile refuses every handoff; a 0.19
overhead is refused under default policy; `checkpoint_events: ["loop_tripped"]`
refuses `verification_failed`.

### R2 — Wire the verdict and repair state through every entry point

**Files:** `yieldpoint/routingcmd.py`, `yieldpoint/mcp/tools.py`,
`yieldpoint/mcp/schemas.py`, `yieldpoint/langgraph/session.py`,
`yieldpoint/harness/profile.py`, `tests/test_routing_cli.py`, `tests/test_mcp.py`,
`tests/test_langgraph.py`.

1. Add `repair_attempt: int = 0` and `loop_tripped: bool = False` to `ProfileContext`
   and emit them into `verification`.
2. `assess-routing`: add `--verdict FILE` (JSON verdict) and `--repair-attempt`.
   `handoff-check`: add `--overhead`.
3. MCP `yieldpoint_routing_profile`: accept an optional `verdict` object; add
   `estimated_overhead_fraction` to `yieldpoint_handoff_check`.
4. `make_admission_node`: read `VERDICT_KEY`, `ATTEMPTS_KEY`, and `TRIPPED_KEY` from
   graph state and pass them into `ProfileContext`. `make_handoff_router`: pass the
   host's estimated overhead.

**Complete when:** a `block` verdict reaches `human_review` through the CLI, through
MCP, and through the LangGraph admission node — each covered by a test.

### R3 — Respect `enabled`, and close the remaining contract fields

**Files:** `yieldpoint/harness/middleware.py`, `yieldpoint/harness/profile.py`,
`yieldpoint/core/routingsession.py`, `yieldpoint/core/policyfields.py`,
`yieldpoint/harness/capsule.py`, tests.

1. `middleware.assess` attaches `routing_profile` only when
   `policy.routing_session.enabled`. Pass the already-computed `risk` and `tier` into
   `build_profile` rather than recomputing (4.4).
2. Add the `pace` block to the profile, from `harness.pacing.pace`.
3. Add `required_checks` to the `RoutingSession` dataclass and reader, validating keys
   against `CHECKS`, and let it override the hardcoded `required` lists.
4. Fix `_bound`: reserve the digest's length before the size check, or compute the
   digest over the pre-digest encoding and assert the final encoding still fits.
5. Broaden `_language` to the languages the engine actually analyses, and return every
   distinct language present rather than one.
6. Have `validate_profile` recompute and compare `profile_id`, with a documented
   escape for fixtures that deliberately carry a placeholder — or regenerate the
   fixtures with real digests (preferred; see R4).

**Complete when:** default policy (`enabled: false`) produces a `middleware.assess`
result whose key set is exactly `{signals, risk, tier}`, matching pre-feature
behaviour; a capsule never exceeds its declared cap.

### R4 — Restore cross-language parity

**Files:** `sdk/node/src/session.js`, `sdk/node/src/capsule.js`,
`sdk/java/.../RoutingSession.java`, `sdk/java/.../TaskCapsule.java`,
`fixtures/routing-profile/*`, Node and Java tests, `tests/test_routing_profile.py`.

1. Decide and record which of two models applies, because the current code is
   ambiguous about it:
   - *Preferred:* the profile's `handoff` block carries every bound (after R1), so
     Node and Java remain pure transport validators evaluating declared data rather
     than re-deriving rules. This satisfies the non-goal.
   - *Alternative:* Node and Java shell out to `yieldpoint handoff-check`.
   Take the first; it keeps the SDKs dependency-free.
2. Apply the overhead and verdict-status checks in Node and Java so all three agree.
3. Regenerate fixtures with real digests produced by `build_profile`, and add the
   three missing cases: `blocked-profile.json`, `exhausted-session.json`,
   `trimmed-capsule.json`. Wire `unverified-profile.json` into all three languages'
   tests so it stops being dead.
4. Add capsule validation to Node and Java against `trimmed-capsule.json`.
5. Add one test per language asserting the same fixture set yields the same
   allow/deny decision and the same reason category.

**Complete when:** Python, Node, and Java produce identical decisions across all
seven fixtures, and a digest computed in Python validates unchanged in both SDKs.

### R5 — Close the documentation and example gaps

**Files:** `scripts/docs_routing.py`, `docs/routing.html`, `examples/jev_router.py`,
`examples/node/jev_router.mjs`, `examples/java/JevRouter.java`,
`tests/test_jev_example.py`, `yieldpoint/report.py`, `.gitignore`.

1. `docs/routing.html` currently claims the overhead budget is enforced. After R1 that
   becomes true; until then the sentence must not ship. Re-generate the page and add
   the `--overhead`, `--verdict`, and `checkpoint_events` surfaces.
2. Extend every Jev example past `admit` to `can_handoff`, showing an over-confident
   provider answer being refused by the deterministic gate. Assert that refusal in
   `tests/test_jev_example.py`.
3. Either add routing totals to `yieldpoint/report.py` as Stage 7 states, or amend the
   original plan to record that `routing-stats` replaced it deliberately. Do not leave
   the plan and the code disagreeing.
4. Add `.yieldpoint/` to `.gitignore`.

### R6 — Add the negative tests the plan requires

**Files:** `tests/test_routing_profile.py`, `tests/test_routing_cli.py`, SDK tests.

Cover, per the plan's own list: routing every edit is refused; an unbounded transcript
capsule is trimmed rather than accepted; a switch after a pass is refused; a candidate
missing one required capability is refused in Python as it already is in Node;
admission state survives a save/reload round trip and re-routes identically; and a
second handoff after an exhausted budget is refused in all three languages.

### R7 — Repository hygiene

Move `plan/` out of the published tree, consistent with keeping planning documents
internal. This is a repository decision, not a code change, and is listed last so it
does not block the functional work.

---

## What does not need to change

- The `RoutingProfile` schema shape, capability vocabulary, and check vocabulary.
- `core/routingsession.py` bounds and their validation semantics (`0..2` switches,
  `1000..24000` capsule chars, `0..0.20` overhead) — only their *use* is missing.
- The `routingledger` design. Keeping routing facts out of the verification `Event`
  stream was the right call and its redaction is tight.
- The MCP additive-key approach for `yieldpoint_assess`.
- The Jev adapter's default-offline posture and explicit environment opt-in.
- Stage ordering and acceptance-check style in the original plan.
