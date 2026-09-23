# Yieldpoint LangGraph.js adapter

`@tensilestream/yieldpoint-langgraph` places the canonical Yieldpoint verifier
between generation and application in a LangGraph.js workflow. It does not
implement rules in JavaScript: it invokes an installed `yieldpoint` CLI and
adapts its versioned verdict JSON to graph state.

```sh
pipx install yieldpoint
npm install @tensilestream/yieldpoint-langgraph @langchain/langgraph
```

```js
import { verifyNode, makeRouter, PASS, REPAIR, ESCALATE, BLOCK, UNVERIFIED } from "@tensilestream/yieldpoint-langgraph";

graph.addNode("verify", verifyNode({ root: "." }));
graph.addConditionalEdges("verify", makeRouter({ onUnverified: ESCALATE }), {
  [PASS]: "apply", [REPAIR]: "generate", [ESCALATE]: "review",
  [BLOCK]: "review", [UNVERIFIED]: "review",
});
```

Set `executable` and `executableArgs` when `yieldpoint` is not on `PATH`, for
example `{ executable: "python3", executableArgs: ["-m", "yieldpoint"] }`.
The adapter treats a valid JSON verdict as a normal result even when the CLI
exits `1` for a finding.
