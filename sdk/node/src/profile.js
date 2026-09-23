export const ROUTING_PROFILE_SCHEMA_VERSION = 1;

/** Blocks a profile must carry for the gate to have anything to apply. */
const REQUIRED_BLOCKS = ["coverage", "requirements", "handoff", "verification"];

/** Array fields the gate reads directly, checked so a denial is never a crash. */
const REQUIRED_LISTS = [
  ["requirements", "capabilities"],
  ["handoff", "checkpoint_events"],
];

/**
 * Validate transport emitted by the canonical Python CLI; never recalculate it.
 *
 * Structure and pairing are checked here. The `profile_id` digest is verified by
 * the Python engine that produced it: re-deriving it in a second language would
 * mean re-implementing Python's exact JSON number formatting, which is the sort
 * of duplicated rule this contract exists to avoid. Node's job is to carry the
 * document faithfully and apply the bounds it publishes.
 */
function requireBlocks(profile) {
  for (const key of REQUIRED_BLOCKS) {
    if (!profile[key] || typeof profile[key] !== "object") {
      throw new Error(`Yieldpoint routing profile is missing ${key}.`);
    }
  }
}

function requireLists(profile) {
  for (const [block, field] of REQUIRED_LISTS) {
    if (!Array.isArray(profile[block][field])) {
      throw new Error(`Yieldpoint routing profile ${block}.${field} must be an array.`);
    }
  }
}

export function validateRoutingProfile(profile) {
  if (!profile || typeof profile !== "object" || profile.schema_version !== ROUTING_PROFILE_SCHEMA_VERSION) {
    throw new Error("Unsupported Yieldpoint routing profile schema.");
  }
  if (typeof profile.profile_id !== "string" || !profile.profile_id) {
    throw new Error("Yieldpoint routing profile is missing profile_id.");
  }
  requireBlocks(profile);
  requireLists(profile);
  return profile;
}
