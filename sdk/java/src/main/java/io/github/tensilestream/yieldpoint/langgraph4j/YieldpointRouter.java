package io.github.tensilestream.yieldpoint.langgraph4j;

import java.util.Map;
import org.bsc.langgraph4j.action.EdgeAction;
import org.bsc.langgraph4j.state.AgentState;

/** Routes a graph only after the canonical verifier has supplied a verdict. */
public final class YieldpointRouter {
  public static final String PASS = "pass", UNVERIFIED = "unverified", REPAIR = "repair",
      ESCALATE = "escalate", BLOCK = "block";
  private final int maxRepairs;
  private final String onUnverified, onExhausted, onStalled;

  public YieldpointRouter() { this(3, UNVERIFIED, ESCALATE, ESCALATE); }
  public YieldpointRouter(int maxRepairs, String onUnverified, String onExhausted, String onStalled) {
    this.maxRepairs = maxRepairs; this.onUnverified = onUnverified;
    this.onExhausted = onExhausted; this.onStalled = onStalled;
  }
  public String route(Map<String, Object> state) {
    Object raw = state.get("verdict");
    String status = raw instanceof YieldpointVerdict verdict ? verdict.status()
        : raw instanceof Map<?, ?> map && map.get("status") instanceof String value ? value : UNVERIFIED;
    if (UNVERIFIED.equals(status)) return onUnverified;
    if (!REPAIR.equals(status)) return status;
    if (Boolean.TRUE.equals(state.get("yieldpoint_loop_tripped"))) return onStalled;
    Object attempts = state.getOrDefault("yieldpoint_attempts", 0);
    return attempts instanceof Number number && number.intValue() >= maxRepairs ? onExhausted : REPAIR;
  }
  /** Adapter accepted directly by {@code StateGraph.addConditionalEdges}. */
  public EdgeAction<AgentState> asLangGraphEdge() { return state -> route(state.data()); }
}
