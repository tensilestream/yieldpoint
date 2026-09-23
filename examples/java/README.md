# Java adapter example

The Java adapter delegates verification to the same `yieldpoint` executable as
Python and Node. Configure `YieldpointVerifier` with `List.of("python3", "-m",
"yieldpoint")` during local development, add `YieldpointVerificationNode` to
the graph before applying a candidate change, then route with `YieldpointRouter`.

[`LangGraphRepairLoop.java`](LangGraphRepairLoop.java) is the complete graph
shape. It keeps a plain JSON-compatible `verdict` map in state, so standard
LangGraph4j checkpointers can persist it. The `prescription` field is derived
from the canonical verdict findings and can be passed directly to a repair
agent.

[`JevRouter.java`](JevRouter.java) demonstrates the optional routing boundary:
validate the canonical profile, filter candidates locally by required
capabilities, and call `RoutingSession.canHandoff` at a real checkpoint. Keep
Jev credentials and HTTP calls in the host application; Yieldpoint itself does
not receive them or contact a provider.
