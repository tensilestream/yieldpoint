package example;

import io.github.tensilestream.yieldpoint.langgraph4j.YieldpointRouter;
import io.github.tensilestream.yieldpoint.langgraph4j.YieldpointVerificationNode;
import io.github.tensilestream.yieldpoint.langgraph4j.YieldpointVerifier;
import java.util.Map;
import org.bsc.langgraph4j.GraphDefinition;
import org.bsc.langgraph4j.StateGraph;
import org.bsc.langgraph4j.action.AsyncNodeAction;
import org.bsc.langgraph4j.state.AgentState;

/**
 * Add the verifier between a generator and any change-application node. The
 * adapter invokes the canonical CLI; this program contains no Yieldpoint rule.
 */
public final class LangGraphRepairLoop {
  public static void main(String[] args) throws Exception {
    var verify = new YieldpointVerificationNode(new YieldpointVerifier());
    var router = new YieldpointRouter(3, "review", "human", "human");
    var graph = new StateGraph<AgentState>(AgentState::new)
        .addNode("verify", AsyncNodeAction.node_async(verify.asLangGraphNode()))
        .addEdge(GraphDefinition.START, "verify")
        .addConditionalEdges("verify", router.asLangGraphEdge(), Map.of(
            "pass", GraphDefinition.END, "repair", "repair", "block", "human",
            "escalate", "human", "review", "human", "unverified", "human"));
    // A caller supplies either a unified "diff" or a "changes" list in graph state.
    System.out.println(graph.compile().invoke(Map.of()).orElseThrow().data());
  }
}
