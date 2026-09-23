package example;

import io.github.tensilestream.yieldpoint.langgraph4j.RoutingProfile;
import io.github.tensilestream.yieldpoint.langgraph4j.RoutingSession;
import java.util.List;
import java.util.Map;

/**
 * Optional-provider shape: capability filtering stays local, and the host may
 * submit only this bounded metadata to Jev after explicit credential opt-in.
 *
 * <p>The profile below carries the same {@code handoff} bounds the CLI publishes.
 * Those bounds are what the gate applies — a host that invents its own profile
 * is inventing its own limits, which is exactly what this contract prevents.
 */
public final class JevRouter {
  public static void main(String[] args) {
    RoutingProfile profile = RoutingProfile.fromMap(Map.of(
        "schema_version", 1, "profile_id", "sha256:example", "coverage", Map.of(),
        "requirements", Map.of("capabilities", List.of("code_generation", "tool_use")),
        "verification", Map.of("status", "repair"),
        "handoff", Map.of(
            "max_model_switches", 1,
            "capsule_max_chars", 12000,
            "checkpoint_events", List.of("verification_failed", "repair_exhausted", "loop_tripped"),
            "max_overhead_fraction", 0.05,
            "allow_unverified", false)));
    RoutingSession session = RoutingSession.fromMap(Map.of(
        "routing_session_version", 1, "task_id", "example", "profile_id", profile.profileId(),
        "switch_count", 0));

    // A router's answer is an input, never an authorization.
    var refused = session.canHandoff(profile, "verification_failed", List.of("code_generation"), 0.03);
    var allowed = session.canHandoff(profile, "verification_failed", List.of("code_generation", "tool_use"), 0.03);
    var overBudget = session.canHandoff(profile, "verification_failed", List.of("code_generation", "tool_use"), 0.19);

    System.out.println("under-qualified candidate allowed: " + refused.allowed() + " (" + refused.reason() + ")");
    System.out.println("qualified candidate allowed: " + allowed.allowed());
    System.out.println("over-budget routing overhead allowed: " + overBudget.allowed());
    System.out.println("Set provider credentials in the host application, never in Yieldpoint config.");
  }
}
