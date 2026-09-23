# Yieldpoint LangGraph4j adapter

This thin Java adapter calls the installed `yieldpoint` CLI; it does not port
or duplicate any verification rules. Add it to a graph as a state-to-update
function, configure `YieldpointVerifier` with an executable command when needed,
and route on the returned `verdict.status`.
