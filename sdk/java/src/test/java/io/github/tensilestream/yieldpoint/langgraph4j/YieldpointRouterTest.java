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
    Path repository = Path.of("").toAbsolutePath().normalize();
    var client = new YieldpointVerifier(List.of("yieldpoint"), Duration.ofSeconds(15), repository);
    var node = new YieldpointVerificationNode(client);
    Map<String, Object> update = node.apply(Map.of("changes", List.of(Map.of(
        "path", "src/invoice.py", "before", "def total():\n    return 41\n",
        "after", "def total():\n    return 42\n")), "root", repository.toString()));
    Map<?, ?> verdict = (Map<?, ?>) update.get("verdict");
    assertEquals(4, ((Number) verdict.get("schema_version")).intValue());
    assertEquals("pass", verdict.get("status"));
    assertEquals("", update.get("prescription"));
  }

  @Test void accepts_the_shared_routing_profile_and_session_fixture() throws Exception {
    RoutingProfile profile = RoutingProfile.fromMap(fixture("valid-profile.json"));
    RoutingSession session = RoutingSession.fromMap(fixture("valid-session.json"));
    assertEquals(profile.profileId(), session.profileId());
    assertEquals(true, session.canHandoff(profile, "verification_failed", List.of("code_generation")).allowed());
  }

  @Test void rejects_the_shared_invalid_routing_profile_fixture() throws Exception {
    org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class,
        () -> RoutingProfile.fromMap(fixture("invalid-profile.json")));
  }

  private static Map<String, Object> fixture(String name) throws Exception {
    Path path = Path.of("..", "..", "fixtures", "routing-profile", name);
    return JSON.readValue(path.toFile(), new TypeReference<>() { });
  }
}
