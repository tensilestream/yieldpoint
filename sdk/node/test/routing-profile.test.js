import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { canHandoff, validateRoutingProfile, validateRoutingSession } from "../src/index.js";

const fixture = (name) => JSON.parse(readFileSync(join("..", "..", "fixtures", "routing-profile", name), "utf8"));

test("shared valid profile and session fixtures are accepted", () => {
  const profile = validateRoutingProfile(fixture("valid-profile.json"));
  const session = validateRoutingSession(fixture("valid-session.json"));
  assert.equal(profile.profile_id, session.profile_id);
});

test("shared invalid profile fixture is rejected", () => {
  assert.throws(() => validateRoutingProfile(fixture("invalid-profile.json")), /Unsupported/);
});

test("handoff requires a configured checkpoint and capabilities", () => {
  const profile = fixture("valid-profile.json");
  const session = fixture("valid-session.json");
  assert.equal(canHandoff(session, profile, { event: "normal_work" }).allowed, false);
  assert.equal(canHandoff(session, profile, {
    event: "verification_failed", candidateCapabilities: ["code_generation"],
  }).allowed, true);
});
