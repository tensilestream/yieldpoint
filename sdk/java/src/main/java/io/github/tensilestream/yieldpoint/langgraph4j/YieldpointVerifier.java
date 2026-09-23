package io.github.tensilestream.yieldpoint.langgraph4j;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.CompletableFuture;

/** CLI client only: no policy, parser, rule, or verdict logic lives in Java. */
public final class YieldpointVerifier {
  private final List<String> command;
  private final Duration timeout;
  private final Path workingDirectory;

  public YieldpointVerifier() { this(List.of("yieldpoint"), Duration.ofSeconds(10), null); }
  public YieldpointVerifier(List<String> command, Duration timeout) {
    this(command, timeout, null);
  }
  public YieldpointVerifier(List<String> command, Duration timeout, Path workingDirectory) {
    this.command = List.copyOf(command); this.timeout = timeout; this.workingDirectory = workingDirectory;
  }
  public YieldpointVerdict verifyDiff(String diff, String root, String policy) throws IOException, InterruptedException {
    List<String> args = new ArrayList<>(command);
    args.addAll(List.of("check", "--diff", "-", "--root", root == null ? "." : root));
    if (policy != null && !policy.isBlank()) args.addAll(List.of("--policy", policy));
    args.add("--json");
    return execute(args, diff);
  }
  public YieldpointVerdict verifyChange(String path, String before, String after, String root, String policy) throws IOException, InterruptedException {
    Path directory = Files.createTempDirectory("yieldpoint-java-");
    try {
      Path beforeFile = directory.resolve("before"), afterFile = directory.resolve("after");
      Files.writeString(beforeFile, before == null ? "" : before, StandardCharsets.UTF_8);
      Files.writeString(afterFile, after == null ? "" : after, StandardCharsets.UTF_8);
      List<String> args = new ArrayList<>(command);
      args.addAll(List.of("check", "--path", path, "--before", beforeFile.toString(), "--after", afterFile.toString(), "--root", root == null ? "." : root));
      if (policy != null && !policy.isBlank()) args.addAll(List.of("--policy", policy));
      args.add("--json");
      return execute(args, "");
    } finally {
      Files.deleteIfExists(directory.resolve("before")); Files.deleteIfExists(directory.resolve("after")); Files.deleteIfExists(directory);
    }
  }
  private YieldpointVerdict execute(List<String> args, String input) throws IOException, InterruptedException {
    ProcessBuilder builder = new ProcessBuilder(args).redirectErrorStream(true);
    if (workingDirectory != null) builder.directory(workingDirectory.toFile());
    Process process = builder.start();
    CompletableFuture<byte[]> outputBytes = CompletableFuture.supplyAsync(() -> {
      try { return process.getInputStream().readAllBytes(); }
      catch (IOException error) { throw new IllegalStateException(error); }
    });
    process.getOutputStream().write(input.getBytes(StandardCharsets.UTF_8));
    process.getOutputStream().close();
    if (!process.waitFor(timeout.toMillis(), TimeUnit.MILLISECONDS)) {
      process.destroyForcibly(); throw new IOException("Yieldpoint timed out after " + timeout);
    }
    String output;
    try { output = new String(outputBytes.join(), StandardCharsets.UTF_8); }
    catch (Exception error) { throw new IOException("Could not read Yieldpoint output", error); }
    // Exit 1 is a finding, not a transport error. Parsing is authoritative.
    return YieldpointVerdict.parse(output);
  }
}
