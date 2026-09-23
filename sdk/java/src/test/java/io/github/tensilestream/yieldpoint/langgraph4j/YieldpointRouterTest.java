package io.github.tensilestream.yieldpoint.langgraph4j;

import static org.junit.jupiter.api.Assertions.assertEquals;
import java.nio.file.Path;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.bsc.langgraph4j.state.AgentState;
import org.bsc.langgraph4j.StateGraph;
import org.bsc.langgraph4j.GraphDefinition;
import org.bsc.langgraph4j.action.AsyncNodeAction;

class YieldpointRouterTest {
  private static final ObjectMapper JSON = new ObjectMapper();
  private static YieldpointVerdict verdict(String status) {
    return YieldpointVerdict.parse("{\"schema_version\":4,\"status\":\"" + status
        + "\",\"findings\":[],\"checked\":[],\"skipped\":[],\"acknowledged\":[]}");
  }

  @Test void routes_unverified_explicitly() {
    assertEquals("unverified", new YieldpointRouter().route(Map.of("verdict", verdict("unverified"))));
  }

  @Test void escalates_exhausted_repair() {
    assertEquals("escalate", new YieldpointRouter().route(Map.of("verdict", verdict("repair"), "yieldpoint_attempts", 3)));
  }

  @Test void exposes_a_real_langgraph4j_edge_action() throws Exception {
    var state = new AgentState(Map.of("verdict", verdict("unverified")));
    assertEquals("unverified", new YieldpointRouter().asLangGraphEdge().apply(state));
  }

  @Test void runs_as_a_real_langgraph4j_graph_node() throws Exception {
    var verifier = new YieldpointVerificationNode(new YieldpointVerifier());
    var graph = new StateGraph<AgentState>(AgentState::new)
        .addNode("verify", AsyncNodeAction.node_async(verifier.asLangGraphNode()))
        .addEdge(GraphDefinition.START, "verify")
        .addEdge("verify", GraphDefinition.END);
    var result = graph.compile().invoke(Map.of()).orElseThrow();
    assertEquals("unverified", ((Map<?, ?>) result.data().get("verdict")).get("status"));
  }

  @Test void executes_the_canonical_cli_and_keeps_a_json_safe_verdict() {
    Path repository = findRepositoryRoot();
    var client = new YieldpointVerifier(resolveCliCommand(repository), Duration.ofSeconds(15), repository);
    var node = new YieldpointVerificationNode(client);
    Map<String, Object> update = node.apply(Map.of("changes", List.of(Map.of(
        "path", "src/invoice.py", "before", "def total():\n    return 41\n",
        "after", "def total():\n    return 42\n")), "root", repository.toString()));
    Map<?, ?> verdict = (Map<?, ?>) update.get("verdict");
    assertEquals(4, ((Number) verdict.get("schema_version")).intValue());
    assertEquals("pass", verdict.get("status"));
    assertEquals("", update.get("prescription"));
  }

  private static Path findRepositoryRoot() {
    Path here = Path.of("").toAbsolutePath().normalize();
    if (java.nio.file.Files.isDirectory(here.resolve("yieldpoint"))) return here;
    Path parent = here.resolve("../..").normalize();
    if (java.nio.file.Files.isDirectory(parent.resolve("yieldpoint"))) return parent;
    return here;
  }

  private static List<String> resolveCliCommand(Path repository) {
    String override = System.getenv("YIELDPOINT_BIN");
    if (override != null && !override.isBlank()) return List.of(override);
    if (canRun(List.of("yieldpoint", "--version"), repository)) return List.of("yieldpoint");
    if (canRun(List.of("python3", "-m", "yieldpoint", "--version"), repository)) {
      return List.of("python3", "-m", "yieldpoint");
    }
    if (canRun(List.of("python", "-m", "yieldpoint", "--version"), repository)) {
      return List.of("python", "-m", "yieldpoint");
    }
    return List.of("yieldpoint");
  }

  private static boolean canRun(List<String> command, Path cwd) {
    try {
      Process process = new ProcessBuilder(command).directory(cwd.toFile()).start();
      return process.waitFor(5, java.util.concurrent.TimeUnit.SECONDS) && process.exitValue() == 0;
    } catch (Exception e) {
      return false;
    }
  }

  /** Everything the decision table can ask for, so one condition is tested at a time. */
  private static final List<String> ALL = List.of(
      "tool_use", "strong_reasoning", "large_context", "code_generation", "multilingual_sdk");

  @Test void accepts_the_shared_routing_profile_and_session_fixture() throws Exception {
    RoutingProfile profile = RoutingProfile.fromMap(fixture("valid-profile.json"));
    RoutingSession session = RoutingSession.fromMap(fixture("valid-session.json"));
    assertEquals(profile.profileId(), session.profileId());
    assertEquals(true, session.canHandoff(profile, "verification_failed", ALL).allowed());
  }

  @Test void rejects_the_shared_invalid_routing_profile_fixture() throws Exception {
    org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class,
        () -> RoutingProfile.fromMap(fixture("invalid-profile.json")));
  }

  @Test void refuses_a_handoff_outside_a_configured_checkpoint() throws Exception {
    RoutingProfile profile = RoutingProfile.fromMap(fixture("valid-profile.json"));
    RoutingSession session = RoutingSession.fromMap(fixture("valid-session.json"));
    assertEquals(false, session.canHandoff(profile, "normal_work", ALL).allowed());
  }

  @Test void refuses_to_escalate_a_change_no_rule_verified() throws Exception {
    RoutingProfile profile = RoutingProfile.fromMap(fixture("unverified-profile.json"));
    RoutingSession session = RoutingSession.fromMap(sessionFor(profile));
    RoutingSession.Decision decision = session.canHandoff(profile, "verification_failed", ALL);
    assertEquals(false, decision.allowed());
    assertEquals(true, decision.reason().contains("unverified"));
  }

  @Test void never_routes_around_a_blocked_change() throws Exception {
    RoutingProfile profile = RoutingProfile.fromMap(fixture("blocked-profile.json"));
    RoutingSession session = RoutingSession.fromMap(sessionFor(profile));
    assertEquals(false, session.canHandoff(profile, "verification_failed", ALL).allowed());
  }

  @Test void refuses_a_second_handoff_once_the_budget_is_spent() throws Exception {
    RoutingProfile profile = RoutingProfile.fromMap(fixture("valid-profile.json"));
    RoutingSession session = RoutingSession.fromMap(fixture("exhausted-session.json"));
    RoutingSession.Decision decision = session.canHandoff(profile, "verification_failed", ALL);
    assertEquals(false, decision.allowed());
    assertEquals(true, decision.reason().contains("budget is exhausted"));
  }

  @Test void applies_the_overhead_budget_the_profile_publishes() throws Exception {
    RoutingProfile profile = RoutingProfile.fromMap(fixture("valid-profile.json"));
    RoutingSession session = RoutingSession.fromMap(fixture("valid-session.json"));
    assertEquals(false, session.canHandoff(profile, "verification_failed", ALL, 0.19).allowed());
    assertEquals(true, session.canHandoff(profile, "verification_failed", ALL, 0.04).allowed());
  }

  @Test void refuses_a_candidate_missing_one_capability() throws Exception {
    RoutingProfile profile = RoutingProfile.fromMap(fixture("valid-profile.json"));
    RoutingSession session = RoutingSession.fromMap(fixture("valid-session.json"));
    assertEquals(false, session.canHandoff(profile, "verification_failed", List.of("tool_use")).allowed());
  }

  @Test void refuses_a_session_paired_with_another_profile() throws Exception {
    RoutingProfile other = RoutingProfile.fromMap(fixture("unverified-profile.json"));
    RoutingSession session = RoutingSession.fromMap(fixture("valid-session.json"));
    assertEquals(false, session.canHandoff(other, "verification_failed", ALL).allowed());
  }

  /** A session bound to the given profile, so identity is not the thing under test. */
  private static Map<String, Object> sessionFor(RoutingProfile profile) throws Exception {
    Map<String, Object> session = new java.util.HashMap<>(fixture("valid-session.json"));
    session.put("profile_id", profile.profileId());
    return session;
  }

  private static Map<String, Object> fixture(String name) throws Exception {
    Path path = Path.of("..", "..", "fixtures", "routing-profile", name);
    return JSON.readValue(path.toFile(), new TypeReference<>() { });
  }
}
