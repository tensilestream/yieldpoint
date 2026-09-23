// Run from the repository root after `npm install --prefix sdk/node`.
// The verifier is the installed Python CLI; JavaScript owns only graph wiring.
import { verifyNode, makeRouter, PASS, REPAIR, ESCALATE, BLOCK, UNVERIFIED } from "../../sdk/node/src/index.js";

const state = {
  changes: [{
    path: "tests/test_invoice.py",
    before: "def test_total():\n    assert total == 42\n",
    after: "def test_total():\n    assert total is not None\n",
  }],
};

const verify = verifyNode({ executable: "python3", executableArgs: ["-m", "yieldpoint"], cwd: process.cwd(), root: process.cwd() });
Object.assign(state, await verify(state));
const route = makeRouter({ onUnverified: ESCALATE })(state);
console.log({ status: state.verdict.status, route, prescription: state.prescription });

if (![PASS, REPAIR, ESCALATE, BLOCK, UNVERIFIED].includes(route)) throw new Error("unexpected route");
