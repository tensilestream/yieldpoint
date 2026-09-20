# Yieldpoint for VS Code

Findings from `yieldpoint` in the Problems panel. The analysis is the same
deterministic engine the CLI and the MCP server use — this extension only
renders it. No model is called.

## Requirements

`yieldpoint` on your `PATH` (`pip install yieldpoint`), and a `.yieldpoint.json`
in the workspace. Set `yieldpoint.executable` if it lives somewhere else.

## Commands

| command | runs |
|---|---|
| Yieldpoint: Review uncommitted changes | `yieldpoint review --json` |
| Yieldpoint: Scan the whole workspace | `yieldpoint scan . --json` |

Review also runs on save, unless `yieldpoint.runOnSave` is off.

## How findings are rendered

Severity follows confidence, not how bad a finding sounds. Only `exact`
findings may block in the engine, so only they appear as errors or warnings;
`lexical` and `external` findings advise and are shown as information.

Files nothing could analyse are listed too, as `not_evaluated`. They are **not
passes**, and an empty Problems panel that hid them would be the same defect
this tool exists to report. If the executable cannot run at all, the status bar
says so rather than showing a clean panel.
