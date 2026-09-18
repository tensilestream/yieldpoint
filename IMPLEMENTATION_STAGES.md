# Implementation Stages

Each stage has a **gate**: something observable that proves it works. No stage starts
before the previous gate passes. Strategy and rationale live in
[PLAN_AND_POSITIONING.md](./PLAN_AND_POSITIONING.md); this file is the build order.

**The MVP is Stage 5** — the point at which this repository can verify edits inside a live
Claude Code session.

---

## Sequencing insight

`verify_change(before_source, after_source, path)` is the core primitive.
`verify_diff(unified_diff)` is a *wrapper* that reconstructs before/after from a patch.

That ordering matters: a Claude Code `PreToolUse` hook supplies before and after content
directly — the `Edit` tool gives `old_string`/`new_string` against a file already on disk,
and `Write` gives full new content against the existing file. **Neither needs a diff
parser.** So the hook surface is reachable before `diff.py` exists, and the first usable
build lands at Stage 5 instead of after the CI path.

---

## Stage 0 — Contract and policy ✅ complete

`verdict.py`, `glob.py`, `policy.py`, `pyproject.toml`.

**Gate:** tests pass; AegisFlow's own `.aegisflow.json` loads warning-free. ✅

---

## Stage 1 — Canonical assertions ✅

`core/relation.py` — the partial order over assertion relations.
`core/assertions.py` — Python AST extraction into `(subject, relation, expected)` triples,
with effective strength downgraded for dead or exception-swallowed paths.

**Gate:** given a test file, the extractor returns the correct triple for every supported
assertion form — bare `assert`, comparisons, membership, `unittest` methods,
`pytest.raises` — and reports `NONE` strength for an assertion whose failure cannot
propagate.

---

## Stage 2 — Monotonicity ✅

`core/monotonicity.py` — pair test functions across before/after (by qualified name, then
by structural similarity), then run the per-subject domination check.

**Gate, both directions:**
- the weakening corpus (delete, downgrade, skip, tautology, swallow) produces findings;
- the legitimate-refactor corpus (parametrize, rename, split, consolidate, reformat)
  produces **zero** findings.

The second half is the real gate. A checker that only catches tampering is easy; one that
does so without crying wolf on ordinary refactors is the product.

---

## Stage 3 — Verification entry point ✅

`core/testintegrity.py` — vacuous assertions, newly-added skip markers, emptied bodies,
swallowed exceptions.
`verify.py` — `verify_change(before, after, path, policy) -> Verdict`, applying policy
severities and recording `checked`/`skipped`.

**Gate:** one call on a file pair returns a correct, policy-driven `Verdict`.

---

## Stage 4 — CLI ✅

`cli.py` — `aegisflow check --path P --before A --after B [--json]`, exit code 0 on pass
and 1 on findings.

**Gate:** runnable from a shell by any language; `--json` emits the versioned verdict schema.

---

## Stage 5 — **MVP: Claude Code hook** ✅ 🎯

`hook.py` — reads a `PreToolUse` payload on stdin, reconstructs before/after for `Edit`,
`MultiEdit` and `Write`, and returns a deny decision with the prescription attached.
`aegisflow install-hook` writes the settings entry.

**Gate — the one that matters:** in a live Claude Code session, an agent attempting to
weaken an assertion in a protected test file is **denied**, and is told which subject was
downgraded and what to restore. Verified by doing it, not by asserting it.

At this point the tool is genuinely usable, on this repository, by the person who asked
for it.

**Install:**

```sh
pip install -e .              # or: export PYTHONPATH=$PWD
aegisflow install-hook        # add --advisory to report without denying
```

Then start a new Claude Code session. `aegisflow install-hook` backs up any existing
`.claude/settings.json` before writing, and re-running it replaces rather than duplicates
the entry.

**Verified end to end:** a weakening `Edit` exits 2 with the prescription on stderr; a
strengthening edit, a non-test file, and a `Bash` call all exit 0. 170 tests pass.

---

## Stage 6 — Diff path

`core/diff.py` — unified-diff parsing; `verify_diff()` over a change set.

**Gate:** a real PR diff that weakens a test exits non-zero and names file and line; a
clean diff exits zero. Enables pre-commit and CI.

---

## Stage 7 — LangGraph node

`langgraph/node.py`, `router.py`, `breaker.py`, plus a runnable example.

**Gate:** an agent that tries to weaken a test is routed to `repair` with the prescription
in state, and converges. Model-call count measured with the node in and out — the cost
claim in PLAN_AND_POSITIONING.md section 4.1 is measured here or dropped.

---

## Stage 8 — Voice

`Verdict.speak()`, confirmation tokens, mode-dependent severity. See section 9.

**Gate:** a verdict renders as one spoken sentence, and a high-blast-radius change requires
explicit assent before apply.

---

## Not scheduled

TypeScript analysis (lexical, cannot block — enforced by `Finding.__post_init__`), MCP
server, container image, CrewAI/OpenAI-Agents adapters, GitHub Action, VS Code, Chrome,
Rust core. Each is a wrapper over `verify_change`; none is a prerequisite for the others.
