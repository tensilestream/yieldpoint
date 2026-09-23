import { validateRoutingProfile } from "./profile.js";

export const ROUTING_SESSION_SCHEMA_VERSION = 1;
const CHECKPOINTS = new Set(["verification_failed", "repair_exhausted", "loop_tripped", "user_requested"]);

export function validateRoutingSession(session) {
  if (!session || typeof session !== "object" || session.routing_session_version !== ROUTING_SESSION_SCHEMA_VERSION) {
    throw new Error("Unsupported Yieldpoint routing session schema.");
  }
  if (!session.task_id || !session.profile_id || !Number.isInteger(session.switch_count) || session.switch_count < 0) {
    throw new Error("Yieldpoint routing session is missing valid identity fields.");
  }
  return session;
}

/** Return a portable decision; the host remains responsible for model selection. */
export function canHandoff(session, profile, { event, candidateCapabilities = [] } = {}) {
  validateRoutingSession(session);
  validateRoutingProfile(profile);
  if (!CHECKPOINTS.has(event)) return { allowed: false, reason: "unsupported handoff checkpoint" };
  if (session.profile_id !== profile.profile_id) return { allowed: false, reason: "session does not belong to profile" };
  if (session.switch_count >= Number(profile.handoff.max_model_switches || 0)) return { allowed: false, reason: "model-switch budget is exhausted" };
  const required = profile.requirements.capabilities;
  if (required.includes("human_review")) return { allowed: false, reason: "profile requires human review" };
  const missing = required.filter((capability) => !candidateCapabilities.includes(capability));
  return missing.length ? { allowed: false, reason: `candidate lacks ${missing.join(", ")}` }
    : { allowed: true, reason: "explicit checkpoint permits one model handoff" };
}
