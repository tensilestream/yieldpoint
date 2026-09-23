# Java LangGraph4j adapter API

```xml
<dependency>
  <groupId>io.github.tensilestream</groupId>
  <artifactId>yieldpoint-langgraph4j</artifactId>
  <version>0.1.4</version>
</dependency>
```

`YieldpointVerifier` invokes the installed Python CLI; it never implements a
second verifier. `YieldpointVerificationNode` accepts state containing `diff`
or `changes` and returns a partial state update with the unchanged,
JSON-compatible verdict map, prescription, attempts, history, and loop-trip
flag. Route that update with `YieldpointRouter`, mapping `unverified` to a
deliberate review path.

Use `new YieldpointVerifier(List.of("python3", "-m", "yieldpoint"), timeout)`
when the console script is not on `PATH`; the three-argument overload also
accepts a working directory for an in-repository CLI.

## Sticky routing transport

`RoutingProfile.fromMap(profile)` and `RoutingSession.fromMap(session)` accept
only schema-1 data produced by the canonical Python routing-profile command.
They validate and carry state; Java does not copy rule calculation or call a
provider.

```java
RoutingProfile profile = RoutingProfile.fromMap(profileFromYieldpoint);
RoutingSession session = RoutingSession.fromMap(sessionFromCheckpoint);
var decision = session.canHandoff(
    profile, "verification_failed",
    List.of("code_generation", "tool_use", "strong_reasoning"));
```

`decision.allowed()` is true only at an explicit checkpoint, within the
configured switch budget, and when the candidate has every required capability.
Your application chooses the actual model and owns provider credentials.
