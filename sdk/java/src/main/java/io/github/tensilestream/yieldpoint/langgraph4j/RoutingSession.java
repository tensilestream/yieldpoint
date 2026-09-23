package io.github.tensilestream.yieldpoint.langgraph4j;

import java.util.List;
import java.util.Map;
import java.util.Set;

/** Portable sticky-session state; a host owns the selected model and provider. */
public record RoutingSession(Map<String, Object> data, String profileId, int switchCount) {
  public static final int SCHEMA_VERSION = 1;

  /** Events a host may spell. Which are live comes from the profile's policy. */
  private static final Set<String> CHECKPOINTS = Set.of(
      "verification_failed", "repair_exhausted", "loop_tripped", "user_requested");

  /** Verdicts that settle a task rather than opening one. */
  private static final Set<String> SETTLED = Set.of("pass", "block");

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

  /**
   * Validate a candidate at a checkpoint. This never chooses or invokes a model.
   *
   * <p>Every bound is read from the profile's {@code handoff} block rather than
   * hard-coded here, so this gate and the Python one cannot drift: they apply the
   * same numbers, published by the same policy.
   */
  public Decision canHandoff(RoutingProfile profile, String event, List<String> capabilities) {
    return canHandoff(profile, event, capabilities, 0.0);
  }

  public Decision canHandoff(RoutingProfile profile, String event, List<String> capabilities,
      double estimatedOverheadFraction) {
    if (!profileId.equals(profile.profileId())) {
      return new Decision(false, "session does not belong to profile");
    }
    Map<?, ?> handoff = (Map<?, ?>) profile.data().get("handoff");

    List<?> configured = handoff.get("checkpoint_events") instanceof List<?> events ? events : List.of();
    List<String> live = configured.stream().map(String::valueOf).filter(CHECKPOINTS::contains).toList();
    if (!live.contains(event)) {
      return new Decision(false, "'" + event + "' is not a configured handoff checkpoint; policy allows "
          + (live.isEmpty() ? "none" : String.join(", ", live)));
    }

    int limit = handoff.get("max_model_switches") instanceof Number value ? value.intValue() : 0;
    if (switchCount >= limit) return new Decision(false, "model-switch budget is exhausted");

    Decision settled = settled(profile, handoff);
    if (settled != null) return settled;

    Map<?, ?> requirements = (Map<?, ?>) profile.data().get("requirements");
    List<?> required = (List<?>) requirements.get("capabilities");
    if (required.contains("human_review")) return new Decision(false, "profile requires human review");
    for (Object capability : required) {
      if (!capabilities.contains(String.valueOf(capability))) {
        return new Decision(false, "candidate lacks required capability: " + capability);
      }
    }

    double ceiling = handoff.get("max_overhead_fraction") instanceof Number value ? value.doubleValue() : 0.0;
    if (estimatedOverheadFraction < 0 || estimatedOverheadFraction > ceiling) {
      return new Decision(false, "estimated routing overhead exceeds the " + ceiling + " budget");
    }
    return new Decision(true, "explicit checkpoint permits one model handoff");
  }

  /** Refuse a handoff the verdict has already answered, or has no evidence for. */
  private static Decision settled(RoutingProfile profile, Map<?, ?> handoff) {
    Map<?, ?> verification = profile.data().get("verification") instanceof Map<?, ?> found ? found : Map.of();
    String status = verification.get("status") instanceof String value ? value : "unverified";
    if (SETTLED.contains(status)) {
      return new Decision(false, "a " + status + " verdict does not need another model");
    }
    boolean allowUnverified = handoff.get("allow_unverified") instanceof Boolean flag && flag;
    if ("unverified".equals(status) && !allowUnverified) {
      return new Decision(false,
          "the change is unverified, so there is no evidence a stronger model would help");
    }
    return null;
  }

  public record Decision(boolean allowed, String reason) { }
}
