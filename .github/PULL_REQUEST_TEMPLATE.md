## What this changes

<!-- One or two sentences. What is different afterwards? -->

## Why

<!-- The problem. If this is a new rule, what did it fail to catch before? -->

## Checklist

- [ ] `python -m unittest discover -s tests -t . -q` passes
- [ ] New behaviour has tests **in both directions** — what it must catch, and the
      legitimate code it must not flag (RULES.md section 6)
- [ ] No file exceeds 300 lines of code (RULES.md section 1)
- [ ] No performance figure added without a runnable benchmark (RULES.md section 5)
- [ ] Nothing in the verification path calls a model, reads the clock, or touches the
      network (RULES.md section 4)

### If this adds or changes a rule

- [ ] Findings are **differential** — a problem that predates the change is not blamed on it
- [ ] Severity is configurable, and defaults to `repair` rather than `block`
- [ ] If the analysis can be wrong, findings are marked `LEXICAL` or `UNRESOLVED` so they
      cannot block
- [ ] `CHANGELOG.md` updated under `[Unreleased]`

### If this changes the verdict JSON

- [ ] `SCHEMA_VERSION` bumped in `aegisflow/core/verdict.py` — it is the cross-language
      API, and a binding written against schema 1 must not silently receive schema 2

## False positives

<!-- Every rule has them. Which legitimate code might this flag, and why is that
     acceptable? "None" is rarely the true answer. -->
