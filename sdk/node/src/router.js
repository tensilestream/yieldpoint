import { createHash } from "node:crypto";
import { ESCALATE, PASS, REPAIR, UNVERIFIED, verdictFrom } from "./verdict.js";

export const HISTORY_KEY = "yieldpoint_history";
export const ATTEMPTS_KEY = "yieldpoint_attempts";
export const TRIPPED_KEY = "yieldpoint_loop_tripped";
export const VERDICT_KEY = "verdict";
export const PRESCRIPTION_KEY = "prescription";

export function signature(...parts) {
  const hash = createHash("sha256");
  for (const part of parts) hash.update(`${part || ""}\0`, "utf8");
  return hash.digest("hex").slice(0, 24);
}

export function observe(history, current, { window = 6, maxRepeats = 3 } = {}) {
  const previous = Array.isArray(history) ? history : [];
  const recent = [...previous.slice(window > 1 ? -(window - 1) : 0), current];
  return { history: recent, tripped: recent.filter((item) => item === current).length >= maxRepeats };
}

export function makeRouter({ maxRepairs = 3, verdictKey = VERDICT_KEY,
  onExhausted = ESCALATE, onStalled = ESCALATE, onUnverified = UNVERIFIED } = {}) {
  return (state) => {
    const status = verdictFrom(state, verdictKey).status || PASS;
    if (status === UNVERIFIED) return onUnverified;
    if (status !== REPAIR) return status;
    if (state?.[TRIPPED_KEY]) return onStalled;
    if (Number(state?.[ATTEMPTS_KEY] || 0) >= maxRepairs) return onExhausted;
    return REPAIR;
  };
}

export const routeOnVerdict = (state) => makeRouter()(state);

export function repairContext(state, verdictKey = VERDICT_KEY) {
  const verdict = verdictFrom(state, verdictKey);
  if (!Array.isArray(verdict.findings) || verdict.findings.length === 0) return "";
  const attempt = Number(state?.[ATTEMPTS_KEY] || 1);
  return `Your change was rejected by deterministic verification (attempt ${attempt}). Fix these and try again:\n\n${verdict.prescription || ""}`;
}
