import { verify } from "./cli.js";
import { prescriptionOf } from "./verdict.js";
import { ATTEMPTS_KEY, HISTORY_KEY, PRESCRIPTION_KEY, TRIPPED_KEY, VERDICT_KEY, observe, signature } from "./router.js";

function payload(state) {
  if (state?.diff || state?.yieldpoint_diff) return String(state.diff || state.yieldpoint_diff);
  const changes = state?.changes || state?.yieldpoint_changes || [];
  return changes.map((entry) => `${entry.path || ""}\x01${entry.after || ""}`).join("\x00");
}

export function verifyNode(options = {}) {
  const verdictKey = options.verdictKey || VERDICT_KEY;
  return async (state) => {
    const verdict = await verify(state, options);
    const loop = observe(state?.[HISTORY_KEY], signature(payload(state), JSON.stringify(verdict)), options);
    return {
      [verdictKey]: verdict,
      [PRESCRIPTION_KEY]: prescriptionOf(verdict),
      [HISTORY_KEY]: loop.history,
      [ATTEMPTS_KEY]: Number(state?.[ATTEMPTS_KEY] || 0) + 1,
      [TRIPPED_KEY]: loop.tripped,
    };
  };
}
