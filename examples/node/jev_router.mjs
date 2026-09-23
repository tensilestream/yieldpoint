// Optional Jev routing. Default mode is deterministic and makes no network call.
import { canHandoff, validateRoutingProfile } from "../../sdk/node/src/index.js";

const candidates = [
  { id: "small", capabilities: ["code_generation"] },
  { id: "capable", capabilities: ["code_generation", "tool_use", "strong_reasoning", "large_context", "multilingual_sdk"] },
];

export function choose(profile) {
  const required = profile.requirements.capabilities;
  const eligible = candidates.filter((candidate) => required.every((item) => candidate.capabilities.includes(item)));
  return eligible[0]?.id || ""; // Host may replace this with a Jev call after explicit opt-in.
}

const profile = validateRoutingProfile({
  schema_version: 1, profile_id: "sha256:example", coverage: {},
  requirements: { capabilities: ["code_generation"] }, handoff: { max_model_switches: 1 },
});
const session = { routing_session_version: 1, task_id: "example", profile_id: profile.profile_id, switch_count: 0 };
console.log({ model: choose(profile), handoff: canHandoff(session, profile, {
  event: "verification_failed", candidateCapabilities: ["code_generation"],
}) });
