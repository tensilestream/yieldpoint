import { validateRoutingProfile } from "./profile.js";

export const ROUTING_SESSION_SCHEMA_VERSION = 1;

/** Events a host may spell. Which are live comes from the profile's policy. */
const CHECKPOINTS = new Set(["verification_failed", "repair_exhausted", "loop_tripped", "user_requested"]);

/** Verdicts that settle a task rather than opening one. */
const SETTLED = new Set(["pass", "block"]);

const deny = (reason) => ({ allowed: false, reason });

export function validateRoutingSession(session) {
  if (!session || typeof session !== "object" || session.routing_session_version !== ROUTING_SESSION_SCHEMA_VERSION) {
    throw new Error("Unsupported Yieldpoint routing session schema.");
  }
  if (!session.task_id || !session.profile_id || !Number.isInteger(session.switch_count) || session.switch_count < 0) {
    throw new Error("Yieldpoint routing session is missing valid identity fields.");
  }
  return session;
}

/** Refuse a handoff the verdict has already answered, or has no evidence for. */
function settled(profile, bounds) {
  const status = (profile.verification && profile.verification.status) || "unverified";
  if (SETTLED.has(status)) return deny(`a ${status} verdict does not need another model`);
  if (status === "unverified" && !bounds.allow_unverified) {
    return deny("the change is unverified, so there is no evidence a stronger model would help");
  }
  return null;
}

/** Check the candidate against what the profile says the work needs. */
function capable(profile, candidateCapabilities) {
  const required = profile.requirements.capabilities;
  if (required.includes("human_review")) return deny("profile requires human review");
  const missing = required.filter((capability) => !candidateCapabilities.includes(capability));
  return missing.length ? deny(`candidate lacks required capability: ${missing.join(", ")}`) : null;
}

/** Check the checkpoint is one this policy opened, and the budget is unspent. */
function admissible(session, profile, bounds, event) {
  if (session.profile_id !== profile.profile_id) return deny("session does not belong to profile");
  const live = (bounds.checkpoint_events || []).filter((name) => CHECKPOINTS.has(name));
  if (!live.includes(event)) {
    return deny(`'${event}' is not a configured handoff checkpoint; policy allows ${live.join(", ") || "none"}`);
  }
  if (session.switch_count >= Number(bounds.max_model_switches || 0)) {
    return deny("model-switch budget is exhausted");
  }
  return null;
}

/**
 * Return a portable decision; the host remains responsible for model selection.
 *
 * Every bound is read from the profile's `handoff` block rather than hard-coded
 * here, so this gate and the Python one cannot drift: they are applying the same
 * numbers, published by the same policy, covered by the same digest.
 */
export function canHandoff(session, profile, { event, candidateCapabilities = [], estimatedOverheadFraction = 0 } = {}) {
  validateRoutingSession(session);
  validateRoutingProfile(profile);
  const bounds = profile.handoff;

  const refused = admissible(session, profile, bounds, event)
    || settled(profile, bounds)
    || capable(profile, candidateCapabilities);
  if (refused) return refused;

  const ceiling = Number(bounds.max_overhead_fraction || 0);
  if (!(estimatedOverheadFraction >= 0 && estimatedOverheadFraction <= ceiling)) {
    return deny(`estimated routing overhead exceeds the ${ceiling} budget`);
  }
  return { allowed: true, reason: "explicit checkpoint permits one model handoff" };
}
