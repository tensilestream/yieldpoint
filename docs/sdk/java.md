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
