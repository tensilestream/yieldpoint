# Security policy

## Reporting

Report vulnerabilities privately through GitHub Security Advisories on
[this repository](https://github.com/tensilestream/yieldpoint/security/advisories/new),
not as a public issue.

## Threat model

Yieldpoint reads source code and runs in developer machines and CI, so two properties
matter more than anything else:

**Configuration must never be able to execute code.** `.yieldpoint.json` is repo-committed,
so a rule that could name a command would mean *cloning a repository and running the hook
executes it*. Linter integration may only enable adapters from a curated in-code registry,
and custom rules are declarative. A change that lets configuration specify an executable is
a vulnerability, not a feature.

**Optional linters run external processes.** They are off by default. When enabled,
Yieldpoint runs only curated argv, never through a shell, with a timeout.

**Metrics export runs a command you name, from the environment only.** Setting
`YIELDPOINT_SINK` to a JSON array of argv makes Yieldpoint spawn that command at the end of
a turn and write JSON Lines to its standard input. This is the one place a command can be
named, and it is an environment variable precisely because it must not be a repository's
decision: `.yieldpoint.json` is committed, so a `metrics.sink` key there would let whoever
opened the last pull request run a command on every machine that cloned it. That key is
ignored and reported as a policy warning rather than honoured, and
`tests/test_timeline.py` asserts a committed config cannot execute anything.

The value is parsed as JSON and passed as argv — never word-split, expanded, or run through
a shell — and the subprocess has a timeout. It is still a command you are choosing to run:
treat `YIELDPOINT_SINK` with the same care as any other executable in your environment, and
do not set it from anything a repository supplies.

The verification core makes no network calls and reads no environment, by policy
(`RULES.md` section 4), and the boundary rule in this repository's own `.yieldpoint.json`
enforces it.

## Not vulnerabilities

- A missed detection. Yieldpoint is a best-effort verifier, not a security boundary; use the
  missed-detection issue template.
- A false positive. Important, but a defect — use the false-positive template.
