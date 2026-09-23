package io.github.tensilestream.yieldpoint.langgraph4j;

import java.util.List;
import java.util.Map;

/**
 * Validated transport emitted by the canonical Python routing-profile command.
 *
 * <p>Structure and pairing are checked here. The {@code profile_id} digest is
 * verified by the Python engine that produced it: re-deriving it in a second
 * language would mean re-implementing Python's exact JSON number formatting,
 * which is the sort of duplicated rule this contract exists to avoid. Java's job
 * is to carry the document faithfully and apply the bounds it publishes.
 */
public record RoutingProfile(Map<String, Object> data, String profileId) {
  public static final int SCHEMA_VERSION = 1;

  public static RoutingProfile fromMap(Map<String, Object> data) {
    if (!(data.get("schema_version") instanceof Number version) || version.intValue() != SCHEMA_VERSION) {
      throw new IllegalArgumentException("Unsupported Yieldpoint routing profile schema");
    }
    if (!(data.get("profile_id") instanceof String profileId) || profileId.isBlank()) {
      throw new IllegalArgumentException("Yieldpoint routing profile is missing profile_id");
    }
    for (String key : List.of("coverage", "requirements", "handoff", "verification")) {
      if (!(data.get(key) instanceof Map<?, ?>)) {
        throw new IllegalArgumentException("Yieldpoint routing profile is missing " + key);
      }
    }
    if (!(((Map<?, ?>) data.get("requirements")).get("capabilities") instanceof List<?>)) {
      throw new IllegalArgumentException("Yieldpoint routing profile capabilities must be a list");
    }
    if (!(((Map<?, ?>) data.get("handoff")).get("checkpoint_events") instanceof List<?>)) {
      throw new IllegalArgumentException("Yieldpoint routing profile is missing handoff.checkpoint_events");
    }
    return new RoutingProfile(Map.copyOf(data), profileId);
  }
}
