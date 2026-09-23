import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { canHandoff, validateRoutingProfile, validateRoutingSession } from "../src/index.js";

const fixture = (name) => JSON.parse(readFileSync(join("..", "..", "fixtures", "routing-profile", name), "utf8"));

// Everything the decision table can ask for, so a test about one condition is
// never accidentally a test about a missing capability.
const ALL = ["tool_use", "strong_reasoning", "large_context", "code_generation", "multilingual_sdk"];

test("shared valid profile and session fixtures are accepted", () => {
  const profile = validateRoutingProfile(fixture("valid-profile.json"));
  const session = validateRoutingSession(fixture("valid-session.json"));
  assert.equal(profile.profile_id, session.profile_id);
});

test("shared invalid profile fixture is rejected", () => {
  assert.throws(() => validateRoutingProfile(fixture("invalid-profile.json")), /Unsupported/);
});

test("handoff requires a configured checkpoint", () => {
  const profile = fixture("valid-profile.json");
  const session = fixture("valid-session.json");
  assert.equal(canHandoff(session, profile, { event: "normal_work", candidateCapabilities: ALL }).allowed, false);
  assert.equal(canHandoff(session, profile, { event: "verification_failed", candidateCapabilities: ALL }).allowed, true);
});

test("a candidate missing one capability is refused", () => {
  const profile = fixture("valid-profile.json");
  const result = canHandoff(fixture("valid-session.json"), profile, {
    event: "verification_failed",
    candidateCapabilities: profile.requirements.capabilities.slice(1),
  });
  assert.equal(result.allowed, false);
  assert.match(result.reason, /lacks required capability/);
});

test("an unverified change is not handed to another model", () => {
  const profile = fixture("unverified-profile.json");
  const session = { ...fixture("valid-session.json"), profile_id: profile.profile_id };
  const result = canHandoff(session, profile, { event: "verification_failed", candidateCapabilities: ALL });
  assert.equal(result.allowed, false);
  assert.match(result.reason, /unverified/);
});

test("a blocked change is never routed around", () => {
  const profile = fixture("blocked-profile.json");
  const session = { ...fixture("valid-session.json"), profile_id: profile.profile_id };
  const result = canHandoff(session, profile, { event: "verification_failed", candidateCapabilities: ALL });
  assert.equal(result.allowed, false);
  assert.match(result.reason, /block/);
});

test("an exhausted switch budget refuses a second handoff", () => {
  const result = canHandoff(fixture("exhausted-session.json"), fixture("valid-profile.json"), {
    event: "verification_failed", candidateCapabilities: ALL,
  });
  assert.equal(result.allowed, false);
  assert.match(result.reason, /budget is exhausted/);
});

test("overhead beyond the published budget is refused", () => {
  const profile = fixture("valid-profile.json");
  const session = fixture("valid-session.json");
  assert.equal(canHandoff(session, profile, {
    event: "verification_failed", candidateCapabilities: ALL, estimatedOverheadFraction: 0.19,
  }).allowed, false);
  assert.equal(canHandoff(session, profile, {
    event: "verification_failed", candidateCapabilities: ALL, estimatedOverheadFraction: 0.04,
  }).allowed, true);
});

test("a session cannot be used with another profile", () => {
  const result = canHandoff(fixture("valid-session.json"), fixture("unverified-profile.json"), {
    event: "verification_failed", candidateCapabilities: ALL,
  });
  assert.equal(result.allowed, false);
  assert.match(result.reason, /does not belong/);
});

test("the trimmed capsule kept its objective, criteria and findings", () => {
  const capsule = fixture("trimmed-capsule.json");
  assert.deepEqual(capsule.truncated, ["diff_excerpt"]);
  assert.equal(capsule.diff_excerpt, "");
  assert.ok(capsule.objective.length > 0);
  assert.equal(capsule.verification.findings[0].rule, "boundary_violation");
});
