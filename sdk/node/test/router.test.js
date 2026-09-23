import test from "node:test";
import assert from "node:assert/strict";
import { ESCALATE, PASS, REPAIR, UNVERIFIED, makeRouter, observe, signature, verifyNode, validateVerdict } from "../src/index.js";
const verdict = (status) => ({ schema_version: 4, status, findings: [], checked: [], skipped: [], acknowledged: [] });

test("router preserves unverified as an explicit route", () => {
  assert.equal(makeRouter()({ verdict: verdict(UNVERIFIED) }), UNVERIFIED);
  assert.equal(makeRouter({ onUnverified: ESCALATE })({ verdict: verdict(UNVERIFIED) }), ESCALATE);
});

test("router escalates exhausted repairs", () => {
  assert.equal(makeRouter({ maxRepairs: 3 })({ verdict: verdict(REPAIR), yieldpoint_attempts: 3 }), ESCALATE);
  assert.equal(makeRouter({ maxRepairs: 3 })({ verdict: verdict(REPAIR), yieldpoint_attempts: 2 }), REPAIR);
  assert.equal(makeRouter()({ verdict: verdict(PASS) }), PASS);
});

test("unsupported verdict JSON fails closed", () => {
  assert.throws(() => validateVerdict({ schema_version: 5, status: PASS }), /Unsupported Yieldpoint verdict schema/);
});

test("loop detector trips only on the configured repeat", () => {
  let history = [];
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    const result = observe(history, "same", { maxRepeats: 3 });
    history = result.history;
    assert.equal(result.tripped, attempt === 3);
  }
});

test("signature is stable and the node fails closed when state has no change", async () => {
  assert.equal(signature("a", "b"), signature("a", "b"));
  const update = await verifyNode()({});
  assert.equal(update.verdict.status, UNVERIFIED);
  assert.deepEqual(update.verdict.skipped, ["no change found in state"]);
});
