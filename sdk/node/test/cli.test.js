import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { execFileSync } from "node:child_process";
import { makeRouter, verifyNode } from "../src/index.js";
import { Annotation, END, START, StateGraph } from "@langchain/langgraph";

const root = fileURLToPath(new URL("../../..", import.meta.url));
const fixture = async (name) => JSON.parse(await readFile(join(root, "tests", "fixtures", "langgraph_contract", name), "utf8"));
const python = { executable: "python3", executableArgs: ["-m", "yieldpoint"], cwd: root, root };

test("Node adapter executes the canonical Python CLI for a shared clean fixture", async () => {
  const contract = await fixture("clean_change.json");
  const state = { ...contract.state, ...(await verifyNode(python)(contract.state)) };
  assert.equal(state.verdict.status, contract.expected.status);
  assert.equal(makeRouter()(state), contract.expected.route);
  assert.equal(state.yieldpoint_attempts, contract.expected.attempts);
});

test("Node adapter preserves a CLI finding even when the process exits 1", async () => {
  const state = { changes: [{ path: "tests/test_invoice.py", before: "def test_total():\n    assert total == 42\n", after: "def test_total():\n    assert total is not None\n" }] };
  const update = await verifyNode(python)(state);
  assert.notEqual(update.verdict.status, "pass");
});

test("Node adapter runs as a real LangGraph.js StateGraph node", async () => {
  const State = Annotation.Root({ changes: Annotation(), verdict: Annotation(), prescription: Annotation(),
    yieldpoint_history: Annotation(), yieldpoint_attempts: Annotation(), yieldpoint_loop_tripped: Annotation() });
  const graph = new StateGraph(State)
    .addNode("verify", verifyNode(python))
    .addEdge(START, "verify")
    .addConditionalEdges("verify", makeRouter({ onUnverified: "review" }), { pass: END, review: END, repair: END, escalate: END, block: END })
    .compile();
  const contract = await fixture("clean_change.json");
  const result = await graph.invoke(contract.state);
  assert.equal(result.verdict.status, "pass");
});

test("packed SDK imports in an isolated consumer", async () => {
  const consumer = await mkdtemp(join(tmpdir(), "yieldpoint-node-consumer-"));
  try {
    const env = { ...process.env, npm_config_cache: join(consumer, ".npm-cache") };
    const tarball = execFileSync("npm", ["pack", "--pack-destination", consumer], { cwd: join(root, "sdk", "node"), env, encoding: "utf8" }).trim().split("\n").at(-1);
    await writeFile(join(consumer, "package.json"), '{"type":"module"}\n');
    execFileSync("npm", ["install", "--offline", "--omit=optional", "--ignore-scripts", join(consumer, tarball)], { cwd: consumer, env, stdio: "pipe" });
    const output = execFileSync("node", ["--input-type=module", "-e", 'import { verifyNode } from "@tensilestream/yieldpoint-langgraph"; console.log((await verifyNode()({})).verdict.status)'], { cwd: consumer, encoding: "utf8" });
    assert.equal(output.trim(), "unverified");
  } finally {
    await (await import("node:fs/promises")).rm(consumer, { recursive: true, force: true });
  }
});
