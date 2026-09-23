package io.github.tensilestream.yieldpoint.langgraph4j;

import java.io.IOException;
import java.util.HashMap;
import java.util.Map;
import java.util.function.Function;
import java.security.MessageDigest;
import java.nio.charset.StandardCharsets;
import org.bsc.langgraph4j.action.NodeAction;
import org.bsc.langgraph4j.state.AgentState;

/** A LangGraph4j-compatible node function: state in, partial state update out. */
public final class YieldpointVerificationNode implements Function<Map<String, Object>, Map<String, Object>> {
  private final YieldpointVerifier verifier;
  public YieldpointVerificationNode(YieldpointVerifier verifier) { this.verifier = verifier; }
  /** Adapter accepted directly by {@code StateGraph.addNode}. */
  public NodeAction<AgentState> asLangGraphNode() { return state -> apply(state.data()); }
  @Override public Map<String, Object> apply(Map<String, Object> state) {
    Map<String, Object> update = new HashMap<>();
    try {
      String diff = String.valueOf(state.getOrDefault("diff", state.getOrDefault("yieldpoint_diff", "")));
      YieldpointVerdict verdict;
      if (diff.isEmpty()) { verdict = YieldpointVerdict.unverified("no change found in state"); }
      else verdict = verifier.verifyDiff(diff, String.valueOf(state.getOrDefault("root", ".")), null);
      if (diff.isEmpty() && state.get("changes") instanceof Iterable<?> changes) {
        YieldpointVerdict merged = null;
        for (Object entry : changes) if (entry instanceof Map<?, ?> change) {
          Object path = change.get("path");
          YieldpointVerdict next = path == null ? YieldpointVerdict.unverified("change without a path")
              : verifier.verifyChange(String.valueOf(path), value(change, "before"), value(change, "after"), String.valueOf(state.getOrDefault("root", ".")), null);
          merged = YieldpointVerdict.merge(merged, next);
        }
        if (merged != null) verdict = merged;
      }
      // Plain JSON-compatible maps keep LangGraph checkpointers interoperable across SDKs.
      update.put("verdict", verdict.data()); update.put("prescription", verdict.prescription());
      String fingerprint = fingerprint(diff + "\0" + verdict.data() + "\0");
      java.util.List<String> history = historyOf(state.get("yieldpoint_history"));
      while (history.size() >= 6) history.remove(0); history.add(fingerprint);
      update.put("yieldpoint_history", history); update.put("yieldpoint_loop_tripped", java.util.Collections.frequency(history, fingerprint) >= 3);
      update.put("yieldpoint_attempts", ((Number) state.getOrDefault("yieldpoint_attempts", 0)).intValue() + 1);
      return update;
    } catch (IOException | InterruptedException error) { throw new IllegalStateException("Yieldpoint verification failed", error); }
  }
  private static String fingerprint(String text) {
    try { byte[] bytes = MessageDigest.getInstance("SHA-256").digest(text.getBytes(StandardCharsets.UTF_8));
      StringBuilder out = new StringBuilder(); for (int i = 0; i < 12; i++) out.append(String.format("%02x", bytes[i])); return out.toString();
    } catch (Exception error) { throw new IllegalStateException("SHA-256 is unavailable", error); }
  }
  private static java.util.List<String> historyOf(Object value) {
    java.util.List<String> history = new java.util.ArrayList<>();
    if (value instanceof Iterable<?> entries) for (Object entry : entries) history.add(String.valueOf(entry));
    return history;
  }
  private static String value(Map<?, ?> values, String key) {
    Object value = values.get(key); return value == null ? "" : String.valueOf(value);
  }
}
