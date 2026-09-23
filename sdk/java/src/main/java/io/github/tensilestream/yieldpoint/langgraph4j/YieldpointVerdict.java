package io.github.tensilestream.yieldpoint.langgraph4j;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** Validated transport view of the canonical JSON verdict produced by the CLI. */
public record YieldpointVerdict(Map<String, Object> data, String status, String prescription) {
  public static final int SCHEMA_VERSION = 4;
  private static final Set<String> STATUSES = Set.of("pass", "unverified", "repair", "escalate", "block");
  private static final ObjectMapper JSON = new ObjectMapper();

  public static YieldpointVerdict parse(String json) {
    try {
      Map<String, Object> data = JSON.readValue(json, new TypeReference<LinkedHashMap<String, Object>>() { });
      return fromMap(data);
    } catch (Exception error) {
      throw new IllegalArgumentException("Yieldpoint output is not a supported verdict JSON document", error);
    }
  }

  public static YieldpointVerdict fromMap(Map<String, Object> source) {
    Map<String, Object> data = new LinkedHashMap<>(source);
    if (!(data.get("schema_version") instanceof Number version) || version.intValue() != SCHEMA_VERSION) {
      throw new IllegalArgumentException("Yieldpoint output has an unsupported verdict schema");
    }
    if (!(data.get("status") instanceof String status) || !STATUSES.contains(status)) {
      throw new IllegalArgumentException("Yieldpoint output has an unsupported verdict status");
    }
    for (String key : List.of("findings", "checked", "skipped", "acknowledged")) {
      if (!(data.get(key) instanceof List<?>)) throw new IllegalArgumentException("Yieldpoint output is missing " + key);
    }
    return new YieldpointVerdict(Map.copyOf(data), status, prescriptionOf(data));
  }

  public static YieldpointVerdict unverified(String reason) {
    return fromMap(Map.of("schema_version", SCHEMA_VERSION, "status", "unverified", "findings", List.of(),
        "checked", List.of(), "skipped", List.of(reason), "acknowledged", List.of()));
  }

  /** Merge CLI results only for a multi-file graph state; rules remain in the CLI. */
  public static YieldpointVerdict merge(YieldpointVerdict left, YieldpointVerdict right) {
    if (left == null) return right;
    if (right == null) return left;
    Map<String, Object> merged = new LinkedHashMap<>(left.data());
    merged.put("status", severity(right.status()) > severity(left.status()) ? right.status() : left.status());
    for (String key : List.of("findings", "checked", "skipped", "acknowledged")) {
      List<Object> values = new ArrayList<>((List<?>) left.data().get(key));
      values.addAll((List<?>) right.data().get(key));
      merged.put(key, values);
    }
    return fromMap(merged);
  }

  private static int severity(String status) { return List.of("pass", "unverified", "repair", "escalate", "block").indexOf(status); }
  private static String prescriptionOf(Map<String, Object> data) {
    StringBuilder out = new StringBuilder();
    for (Object item : (List<?>) data.get("findings")) {
      if (!(item instanceof Map<?, ?> finding)) continue;
      if (!out.isEmpty()) out.append('\n');
      out.append(value(finding, "file", "")).append(':')
          .append(value(finding, "line", 1)).append("  [")
          .append(value(finding, "rule", "unknown")).append("] ")
          .append(value(finding, "detail", "")).append("\n    -> ")
          .append(value(finding, "prescription", ""));
    }
    return out.toString();
  }
  private static Object value(Map<?, ?> map, String key, Object fallback) {
    Object value = map.get(key); return value == null ? fallback : value;
  }
}
