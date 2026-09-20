/**
 * Yieldpoint in the Problems panel.
 *
 * The one property this UI must not lose: a file nothing could analyse is not
 * a file that passed. `yieldpoint` reports those separately in `skipped`, and
 * a linter UI that renders only `findings` would quietly turn "not evaluated"
 * into "clean" -- which is the exact failure Yieldpoint exists to catch. So
 * skipped files get a diagnostic of their own, and the status bar reports the
 * verdict rather than a finding count.
 */
import { execFile } from "child_process";
import * as path from "path";
import * as vscode from "vscode";

/** One finding, as `--json` emits it (schema_version 4). */
interface Finding {
  rule: string;
  file: string;
  line: number;
  detail: string;
  prescription: string;
  status: "pass" | "unverified" | "repair" | "escalate" | "block";
  confidence: "exact" | "lexical" | "unresolved" | "external";
  symbol?: string;
}

interface Verdict {
  status: Finding["status"];
  findings: Finding[];
  skipped: string[];
  checked: string[];
  schema_version: number;
}

/**
 * Only `exact` findings are permitted to block, so only they are errors.
 * A weaker analyser advises; rendering its guess as an error would give it
 * authority the engine deliberately withholds.
 */
function severityOf(finding: Finding): vscode.DiagnosticSeverity {
  if (finding.confidence !== "exact") {
    return vscode.DiagnosticSeverity.Information;
  }
  return finding.status === "block" || finding.status === "escalate"
    ? vscode.DiagnosticSeverity.Error
    : vscode.DiagnosticSeverity.Warning;
}

function diagnosticFor(finding: Finding): vscode.Diagnostic {
  const line = Math.max(0, finding.line - 1);
  const diagnostic = new vscode.Diagnostic(
    new vscode.Range(line, 0, line, Number.MAX_SAFE_INTEGER),
    `${finding.detail}\n${finding.prescription}`,
    severityOf(finding),
  );
  diagnostic.source = "yieldpoint";
  diagnostic.code = finding.rule;
  return diagnostic;
}

/** `"path/to/file.py: reason"`, which is how `skipped` entries are shaped. */
function splitSkipped(entry: string): { file: string; reason: string } {
  const at = entry.indexOf(": ");
  return at < 0
    ? { file: entry, reason: "not evaluated" }
    : { file: entry.slice(0, at), reason: entry.slice(at + 2) };
}

function run(root: string, args: string[]): Promise<Verdict> {
  const executable = vscode.workspace
    .getConfiguration("yieldpoint")
    .get<string>("executable", "yieldpoint");
  return new Promise((resolve, reject) => {
    execFile(executable, args, { cwd: root, maxBuffer: 32 * 1024 * 1024 },
      (error, stdout) => {
        // A non-zero exit means findings, not failure: the verdict is on stdout.
        if (!stdout.trim()) {
          reject(error ?? new Error("yieldpoint produced no output"));
          return;
        }
        try {
          resolve(JSON.parse(stdout) as Verdict);
        } catch (parseError) {
          reject(parseError);
        }
      });
  });
}

function publish(verdict: Verdict, root: string, sink: vscode.DiagnosticCollection): void {
  sink.clear();
  const byFile = new Map<string, vscode.Diagnostic[]>();
  const add = (file: string, diagnostic: vscode.Diagnostic) => {
    const key = path.resolve(root, file);
    byFile.set(key, [...(byFile.get(key) ?? []), diagnostic]);
  };

  for (const finding of verdict.findings ?? []) {
    add(finding.file, diagnosticFor(finding));
  }
  for (const entry of verdict.skipped ?? []) {
    const { file, reason } = splitSkipped(entry);
    const notice = new vscode.Diagnostic(
      new vscode.Range(0, 0, 0, 0),
      `Not evaluated: ${reason}. This is not a pass -- no rule could analyse this file.`,
      vscode.DiagnosticSeverity.Information,
    );
    notice.source = "yieldpoint";
    notice.code = "not_evaluated";
    add(file, notice);
  }
  for (const [file, diagnostics] of byFile) {
    sink.set(vscode.Uri.file(file), diagnostics);
  }
}

function describe(verdict: Verdict): string {
  const findings = verdict.findings?.length ?? 0;
  const skipped = verdict.skipped?.length ?? 0;
  if (verdict.status === "unverified") {
    return "$(question) Yieldpoint: nothing evaluated";
  }
  const tail = skipped ? `, ${skipped} not evaluated` : "";
  return findings
    ? `$(warning) Yieldpoint: ${findings} finding(s)${tail}`
    : `$(check) Yieldpoint: no findings${tail}`;
}

export function activate(context: vscode.ExtensionContext): void {
  const sink = vscode.languages.createDiagnosticCollection("yieldpoint");
  const status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  context.subscriptions.push(sink, status);

  const review = async (args: string[]) => {
    const root = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    if (!root) {
      return;
    }
    try {
      const verdict = await run(root, args);
      publish(verdict, root, sink);
      status.text = describe(verdict);
      status.tooltip = `${verdict.checked?.length ?? 0} file(s) checked`;
      status.show();
    } catch (error) {
      // Say so rather than showing a clean panel we did not earn.
      sink.clear();
      status.text = "$(error) Yieldpoint: did not run";
      status.tooltip = String(error);
      status.show();
    }
  };

  context.subscriptions.push(
    vscode.commands.registerCommand("yieldpoint.review", () => review(["review", "--json"])),
    vscode.commands.registerCommand("yieldpoint.scan", () => review(["scan", ".", "--json"])),
    vscode.workspace.onDidSaveTextDocument(() => {
      if (vscode.workspace.getConfiguration("yieldpoint").get<boolean>("runOnSave", true)) {
        void review(["review", "--json"]);
      }
    }),
  );
  void review(["review", "--json"]);
}

export function deactivate(): void {}
