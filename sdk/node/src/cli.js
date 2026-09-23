import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawn } from "node:child_process";
import { mergeVerdicts, prescriptionOf, validateVerdict } from "./verdict.js";

export class YieldpointCLIError extends Error {}
export class YieldpointCLIUnavailableError extends YieldpointCLIError {}
export class YieldpointCLITimeoutError extends YieldpointCLIError {}
export class YieldpointVerdictError extends YieldpointCLIError {}

function processResult(executable, args, input, timeoutMs, cwd) {
  return new Promise((resolve, reject) => {
    const child = spawn(executable, args, { shell: false, cwd, stdio: ["pipe", "pipe", "pipe"] });
    let stdout = "", stderr = "", timedOut = false;
    const timer = setTimeout(() => { timedOut = true; child.kill("SIGTERM"); }, timeoutMs);
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.once("error", (error) => {
      clearTimeout(timer);
      reject(new YieldpointCLIUnavailableError(`Cannot start ${executable}: ${error.message}`, { cause: error }));
    });
    child.once("close", (code) => {
      clearTimeout(timer);
      if (timedOut) return reject(new YieldpointCLITimeoutError(`Yieldpoint exceeded ${timeoutMs}ms.`));
      try {
        resolve({ verdict: validateVerdict(JSON.parse(stdout)), code, stderr });
      } catch (error) {
        reject(new YieldpointVerdictError(`Yieldpoint returned no valid verdict JSON (exit ${code}): ${stderr || stdout}`, { cause: error }));
      }
    });
    child.stdin.end(input || "");
  });
}

function baseArgs(options) {
  const args = [...(options.executableArgs || []), "check", "--root", options.root || "."];
  if (options.policy) args.push("--policy", options.policy);
  args.push("--json");
  return args;
}

async function runOne(change, options) {
  const executable = options.executable || "yieldpoint";
  const timeoutMs = options.timeoutMs || 10_000;
  if (change.diff != null) {
    return processResult(executable, [...baseArgs(options), "--diff", "-"], change.diff, timeoutMs, options.cwd);
  }
  if (!change.path) throw new YieldpointVerdictError("A change entry needs a repository-relative path.");
  const directory = await mkdtemp(join(tmpdir(), "yieldpoint-node-"));
  try {
    const before = join(directory, "before");
    const after = join(directory, "after");
    await writeFile(before, change.before || "", "utf8");
    await writeFile(after, change.after || "", "utf8");
    return await processResult(executable, [...baseArgs(options), "--path", change.path, "--before", before, "--after", after], "", timeoutMs, options.cwd);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
}

export function readChange(state) {
  for (const key of ["diff", "yieldpoint_diff"]) if (state?.[key]) return { diff: state[key] };
  for (const key of ["changes", "yieldpoint_changes"]) if (Array.isArray(state?.[key]) && state[key].length) return { changes: state[key] };
  return null;
}

export async function verify(state, options = {}) {
  const request = options.extract ? options.extract(state) : readChange(state);
  if (!request) return { status: "unverified", findings: [], checked: [], skipped: ["no change found in state"], acknowledged: [], schema_version: 4 };
  if (request.diff != null) return (await runOne(request, options)).verdict;
  let verdict = null;
  for (const change of request.changes || []) verdict = mergeVerdicts(verdict, (await runOne(change, options)).verdict);
  if (verdict) return { ...verdict, prescription: prescriptionOf(verdict) };
  return { status: "unverified", findings: [], checked: [], skipped: ["no change found in state"], acknowledged: [], schema_version: 4 };
}
