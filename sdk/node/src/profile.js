export const ROUTING_PROFILE_SCHEMA_VERSION = 1;

/** Validate transport emitted by the canonical Python CLI; never recalculate it. */
export function validateRoutingProfile(profile) {
  if (!profile || typeof profile !== "object" || profile.schema_version !== ROUTING_PROFILE_SCHEMA_VERSION) {
    throw new Error("Unsupported Yieldpoint routing profile schema.");
  }
  if (typeof profile.profile_id !== "string" || !profile.profile_id) {
    throw new Error("Yieldpoint routing profile is missing profile_id.");
  }
  for (const key of ["coverage", "requirements", "handoff"]) {
    if (!profile[key] || typeof profile[key] !== "object") {
      throw new Error(`Yieldpoint routing profile is missing ${key}.`);
    }
  }
  if (!Array.isArray(profile.requirements.capabilities)) {
    throw new Error("Yieldpoint routing profile capabilities must be an array.");
  }
  return profile;
}
