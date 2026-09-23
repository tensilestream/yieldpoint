# Node LangGraph adapter API

Install the canonical verifier and the adapter:

```sh
pipx install yieldpoint
npm install @tensilestream/yieldpoint-langgraph @langchain/langgraph
```

`verifyNode(options)` returns an async LangGraph.js node. It sends `diff` or
`changes` state to `yieldpoint check --json`, returns its schema-4 verdict under
`verdict`, and adds `prescription`, `yieldpoint_history`,
`yieldpoint_attempts`, and `yieldpoint_loop_tripped`.

```js
import { verifyNode, makeRouter, ESCALATE } from "@tensilestream/yieldpoint-langgraph";

graph.addNode("verify", verifyNode({ root: "." }));
graph.addConditionalEdges("verify", makeRouter({ onUnverified: ESCALATE }), routes);
```

The adapter rejects malformed or unsupported verdict JSON. A valid verdict
whose CLI process exits `1` is a normal finding, not a transport exception.
Set `executable`, `executableArgs`, and `cwd` when the CLI is not on `PATH`.

## Sticky routing transport

`validateRoutingProfile(profile)` and `validateRoutingSession(session)` accept
only schema-1 JSON emitted by the canonical Python CLI. They validate and carry
the data; they do not calculate Yieldpoint rules or contact a model provider.

```js
import { canHandoff, validateRoutingProfile, validateRoutingSession } from "@tensilestream/yieldpoint-langgraph";

const profile = validateRoutingProfile(profileFromYieldpoint);
const session = validateRoutingSession(sessionFromCheckpoint);
const decision = canHandoff(session, profile, {
  event: "verification_failed",
  candidateCapabilities: ["code_generation", "tool_use", "strong_reasoning"],
});
```

`decision.allowed` can only be true at an explicit checkpoint, within the
profile's switch budget, and when the candidate meets every required capability.
The host still selects the actual model and owns provider credentials.
