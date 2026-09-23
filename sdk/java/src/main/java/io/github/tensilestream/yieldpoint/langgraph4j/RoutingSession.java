package io.github.tensilestream.yieldpoint.langgraph4j;

import java.util.List;
import java.util.Map;

/** Portable sticky-session state; a host owns the selected model and provider. */
public record RoutingSession(Map<String, Object> data, String profileId, int switchCount) {
  public static final int SCHEMA_VERSION = 1;
  private static final List<String> CHECKPOINTS = List.of(
      "verification_failed", "repair_exhausted", "loop_tripped", "user_requested");

  public static RoutingSession fromMap(Map<String, Object> data) {
    if (!(data.get("routing_session_version") instanceof Number version) || version.intValue() != SCHEMA_VERSION) {
      throw new IllegalArgumentException("Unsupported Yieldpoint routing session schema");
    }
    if (!(data.get("task_id") instanceof String taskId) || taskId.isBlank()
        || !(data.get("profile_id") instanceof String profileId) || profileId.isBlank()
        || !(data.get("switch_count") instanceof Number count) || count.intValue() < 0) {
      throw new IllegalArgumentException("Yieldpoint routing session is missing valid identity fields");
    }
    return new RoutingSession(Map.copyOf(data), profileId, count.intValue());
  }

  /** Validate a candidate at a checkpoint. This never chooses or invokes a model. */
  public Decision canHandoff(RoutingProfile profile, String event, List<String> capabilities) {
    if (!CHECKPOINTS.contains(event)) return new Decision(false, "unsupported handoff checkpoint");
    if (!profileId.equals(profile.profileId())) return new Decision(false, "session does not belong to profile");
    Map<?, ?> handoff = (Map<?, ?>) profile.data().get("handoff");
    int limit = handoff.get("max_model_switches") instanceof Number value ? value.intValue() : 0;
    if (switchCount >= limit) return new Decision(false, "model-switch budget is exhausted");
    Map<?, ?> requirements = (Map<?, ?>) profile.data().get("requirements");
    List<?> required = (List<?>) requirements.get("capabilities");
    if (required.contains("human_review")) return new Decision(false, "profile requires human review");
    for (Object capability : required) if (!capabilities.contains(String.valueOf(capability))) {
      return new Decision(false, "candidate lacks " + capability);
    }
    return new Decision(true, "explicit checkpoint permits one model handoff");
  }

  public record Decision(boolean allowed, String reason) { }
}
