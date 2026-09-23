/** Public route values. They intentionally mirror Yieldpoint's JSON contract. */
export const PASS = "pass";
export const UNVERIFIED = "unverified";
export const REPAIR = "repair";
export const ESCALATE = "escalate";
export const BLOCK = "block";

const SEVERITY = { [PASS]: 0, [UNVERIFIED]: 1, [REPAIR]: 2, [ESCALATE]: 3, [BLOCK]: 4 };
export const SCHEMA_VERSION = 4;

export function validateVerdict(verdict) {
  if (!verdict || typeof verdict !== "object" || verdict.schema_version !== SCHEMA_VERSION) {
    throw new Error(`Unsupported Yieldpoint verdict schema ${String(verdict?.schema_version)}; expected ${SCHEMA_VERSION}.`);
  }
  if (typeof verdict.status !== "string" || !(verdict.status in SEVERITY)) {
    throw new Error(`Unsupported Yieldpoint verdict status ${String(verdict.status)}.`);
  }
  for (const key of ["findings", "checked", "skipped", "acknowledged"]) {
    if (!Array.isArray(verdict[key])) throw new Error(`Yieldpoint verdict is missing ${key}.`);
  }
  return verdict;
}

export function statusOf(verdict) {
  return validateVerdict(verdict).status;
}

/** Return the unmodified public verdict object already produced by Yieldpoint. */
export function verdictFrom(state, key = "verdict") {
  const verdict = state?.[key];
  return verdict && typeof verdict === "object" ? validateVerdict(verdict)
    : { schema_version: SCHEMA_VERSION, status: PASS, findings: [], checked: [], skipped: [], acknowledged: [] };
}

export function prescriptionOf(verdict) {
  return (verdict.findings || []).flatMap((finding) => {
    const location = `${finding.file || ""}:${finding.line || 1}`;
    return [`${location}  [${finding.rule || "unknown"}] ${finding.detail || ""}`,
      `    -> ${finding.prescription || ""}`];
  }).join("\n");
}

export function mergeVerdicts(left, right) {
  if (!left) return right;
  if (!right) return left;
  const leftStatus = statusOf(left);
  const rightStatus = statusOf(right);
  return {
    ...left,
    status: SEVERITY[rightStatus] > SEVERITY[leftStatus] ? rightStatus : leftStatus,
    findings: [...(left.findings || []), ...(right.findings || [])],
    checked: [...(left.checked || []), ...(right.checked || [])],
    skipped: [...(left.skipped || []), ...(right.skipped || [])],
  };
}
