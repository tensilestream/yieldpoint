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
