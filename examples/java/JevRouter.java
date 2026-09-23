package example;

import io.github.tensilestream.yieldpoint.langgraph4j.RoutingProfile;
import io.github.tensilestream.yieldpoint.langgraph4j.RoutingSession;
import java.util.List;
import java.util.Map;

/**
 * Optional-provider shape: capability filtering stays local, and the host may
 * submit only this bounded metadata to Jev after explicit credential opt-in.
 */
public final class JevRouter {
  public static void main(String[] args) {
    RoutingProfile profile = RoutingProfile.fromMap(Map.of(
        "schema_version", 1, "profile_id", "sha256:example", "coverage", Map.of(),
        "requirements", Map.of("capabilities", List.of("code_generation")),
        "handoff", Map.of("max_model_switches", 1)));
    RoutingSession session = RoutingSession.fromMap(Map.of(
        "routing_session_version", 1, "task_id", "example", "profile_id", profile.profileId(),
        "switch_count", 0));
    var decision = session.canHandoff(profile, "verification_failed", List.of("code_generation"));
    System.out.println("fallback model: small; handoff allowed: " + decision.allowed());
    System.out.println("Set provider credentials in the host application, never in Yieldpoint config.");
  }
}
