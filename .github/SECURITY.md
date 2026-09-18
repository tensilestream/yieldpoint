# Security policy

## Reporting

Report vulnerabilities privately through GitHub Security Advisories on
[this repository](https://github.com/tensilestream/AgeisFlow/security/advisories/new),
not as a public issue.

## Threat model

AegisFlow reads source code and runs in developer machines and CI, so two properties
matter more than anything else:

**Configuration must never be able to execute code.** `.aegisflow.json` is repo-committed,
so a rule that could name a command would mean *cloning a repository and running the hook
executes it*. Linter integration may only enable adapters from a curated in-code registry,
and custom rules are declarative. A change that lets configuration specify an executable is
a vulnerability, not a feature.

**Optional linters run external processes.** They are off by default. When enabled,
AegisFlow runs only curated argv, never through a shell, with a timeout.

The verification core makes no network calls and reads no environment, by policy
(`RULES.md` section 4), and the boundary rule in this repository's own `.aegisflow.json`
enforces it.

## Not vulnerabilities

- A missed detection. AegisFlow is a best-effort verifier, not a security boundary; use the
  missed-detection issue template.
- A false positive. Important, but a defect — use the false-positive template.
