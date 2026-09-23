// Optional Jev routing. Default mode is deterministic and makes no network call.
//
// The profile is read from the shared fixture rather than hand-built, because a
// hand-built one drifts from the contract the CLI actually emits — and the whole
// point of the fixture is that Python, Node and Java agree on it.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { canHandoff, validateRoutingProfile, validateRoutingSession } from "../../sdk/node/src/index.js";

const here = dirname(fileURLToPath(import.meta.url));
const fixture = (name) => JSON.parse(readFileSync(join(here, "..", "..", "fixtures", "routing-profile", name), "utf8"));

const candidates = [
  { id: "small", capabilities: ["code_generation"] },
  { id: "capable", capabilities: ["code_generation", "tool_use", "strong_reasoning", "large_context", "multilingual_sdk"] },
];

export function choose(profile) {
  const required = profile.requirements.capabilities;
  const eligible = candidates.filter((candidate) => required.every((item) => candidate.capabilities.includes(item)));
  return eligible[0]?.id || ""; // Host may replace this with a Jev call after explicit opt-in.
}

const profile = validateRoutingProfile(fixture("valid-profile.json"));
const session = validateRoutingSession(fixture("valid-session.json"));
const model = choose(profile);

// A router's answer is an input, never an authorization. An under-qualified
// candidate is refused here whatever confidence the router reported.
const refused = canHandoff(session, profile, {
  event: "verification_failed", candidateCapabilities: ["code_generation"], estimatedOverheadFraction: 0.03,
});
const allowed = canHandoff(session, profile, {
  event: "verification_failed", candidateCapabilities: profile.requirements.capabilities, estimatedOverheadFraction: 0.03,
});

console.log(JSON.stringify({ model, refused, allowed }, null, 2));
