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

## Stage 6 — Diff path ✅

`core/diff.py` — unified-diff parsing; `verify_diff()` over a change set.

**Gate:** a real PR diff that weakens a test exits non-zero and names file and line; a
clean diff exits zero. Enables pre-commit and CI. ✅

```sh
git diff --cached | aegisflow check --diff -        # pre-commit
git diff origin/main... | aegisflow check --diff - --json   # CI
```

A unified diff carries only hunks, not whole files — so the after-state is read from
disk and the before-state is rebuilt by **reverse-applying the hunks**, which is exact
and needs no git. Verified byte-for-byte against `git show HEAD:<path>` on real
`git diff` output for modified, added and deleted files. A diff that does not line up
with the file raises `PatchError` and the file is recorded as skipped, because a
silently wrong reconstruction would produce a confident wrong verdict.

Subjects are pooled across every changed file before verification, so moving a test
from one file to another is not reported as lost — confirmed against the same change
judged per-file, which does report it.

---

## Stage 7 — LangGraph node ✅

`langgraph/node.py`, `router.py`, `breaker.py`, plus a runnable example.

**Gate:** an agent that tries to weaken a test is routed to `repair` with the prescription
in state, and converges. ✅

**The adapter imports nothing from LangGraph.** A node is a callable `(state) -> dict` and
a conditional edge is a callable `(state) -> str`, so `aegisflow.langgraph` is
framework-shaped but framework-free: fully unit-testable with nothing installed, and usable
by any graph library sharing that convention.

**Verified against real LangGraph 1.2.11**, in a compiled graph, not in theory:

| Scenario | Result |
|---|---|
| Agent weakens a test, then gets the prescription | converges, `applied`, 2 model calls |
| Agent repeats the *identical* cheat | loop breaker trips, `escalated` |
| Agent alternates between two different cheats | breaker does not trip; repair budget exhausts, `escalated` |
| `max_repairs=1` | `escalated` after one attempt |

Those last three matter: the breaker catches *no* progress and the budget catches *slow*
progress. Both terminate, which is what stops a `repair` verdict cycling forever.

**On the cost claim in PLAN_AND_POSITIONING.md section 4.1** — partially settled. That the
prescription costs zero model calls is demonstrated and is a property of the architecture.
That the loop converges in fewer *total* calls is **not** measured: the example's model is
scripted. Section 4.1 has been amended to separate the two rather than let a scripted run
stand in for a benchmark.

---

## Stage 8 — Voice

`Verdict.speak()`, confirmation tokens, mode-dependent severity. See section 9.

**Gate:** a verdict renders as one spoken sentence, and a high-blast-radius change requires
explicit assent before apply.

---

## Stage 9 — Java, and the generated-code problem

Java cannot be added by pointing a parser at `.java` files, because **the source text is
not the program**. Lombok synthesises accessors, `equals`, `hashCode` and builders from
`@Data`. MapStruct synthesises entire mapper implementations from an interface. Neither
appears in the source an analyser reads.

### 9.1. What actually breaks, and what does not

Being precise here matters, because the fix differs per case.

| Concern | Affected? | Why |
|---|---|---|
| Assertion monotonicity | **No** | Subjects are compared as *expressions*. `invoice.getTotal()` is a string to be matched against the other side; the engine never resolves what the method is or where it came from. Code generation is invisible to it. |
| Field ↔ accessor refactor | **Yes** | `invoice.total` → `invoice.getTotal()` reads as one subject lost and another gained. Same class as the subject-aliasing limitation already documented in `tests/test_monotonicity.py`. |
| Boundary / import rules | **Yes** | `InvoiceMapperImpl` exists only in generated output, so an import of it looks unresolvable and would be wrongly flagged. |
| Silent misanalysis | **Yes — the dangerous one** | Analysing a partially-visible program as if it were complete produces a confident wrong verdict. That is the failure mode this project exists to prevent, so it must not be the failure mode it ships with. |

That comparison-over-resolution design is deliberate and should be preserved: the less the
engine resolves, the less generated code can mislead it.

### 9.2. Ask the build, not the framework

The tempting answer is an MCP per framework — Lombok, MapStruct, Immutables, AutoValue,
Dagger, Querydsl, JPA metamodel, Kotlin data classes. That is an unbounded integration
treadmill, and every entry is a separate thing to trust and keep current.

They all converge on one place. Every one of them is a **javac annotation processor**, and
every annotation processor writes real Java source into the build's generated-sources
output:

```
target/generated-sources/annotations/**     # Maven
build/generated/sources/annotationProcessor/**   # Gradle
```

**One integration reads the compiler's own output and covers every processor that exists or
will ever exist.** It is also the authoritative answer rather than a reimplementation of
someone else's code generator, so it cannot drift from what actually compiles.

`delombok` remains available as a fallback for Lombok specifically when no build output is
present.

### 9.3. Staleness is the hard part, and it degrades rather than guesses

Generated sources exist only after a build. Inside an agent loop, before a write, they are
frequently absent or stale — which is exactly when a confident verdict would be most
wrong.

The rule, enforced in code rather than by convention:

- generated sources present and newer than the source that produced them → `Confidence.EXACT`
- absent, stale, or the module declares annotation processors we cannot account for →
  `Confidence.UNRESOLVED`

`Confidence.UNRESOLVED` **cannot block** — `Finding.__post_init__` raises if a finding tries
to. A degraded analysis can advise; it can never stop work. The reasoning is in
`verdict.py` and the guarantee is tested.

### 9.4. Accessor equivalence

A Java language profile normalises `x.total`, `x.getTotal()` and `x.isTotal()` to one
subject, which removes the field↔accessor false positive **without needing Lombok at all**.
Cheap, deterministic, no build dependency. This is the first thing to build in this stage,
because it is the highest value per line of the whole Java effort.

### 9.5. AegisFlow exposes the MCP; it does not consume others

The MCP surface is worth building, inverted from the obvious direction. Its value is not
"verify this edit" — it is **resolution**:

> *"What members does `Invoice` actually have?"*
> → `getTotal(): BigDecimal — generated by Lombok @Data, from target/generated-sources/…`

That is information the agent **cannot obtain by reading the file**, which is precisely the
gap worth filling. One oracle the agent can trust, answering from source plus the build's
real output, instead of eight framework integrations each guessing.

When the answer is unknown, the MCP says so explicitly. An oracle that admits ignorance is
usable; one that guesses is worse than none.

### 9.6. Gate

- A Lombok `@Data` class: accessor-based assertions compare correctly against field-based
  ones, with no false positive.
- A MapStruct mapper: imports of the generated `*Impl` do not raise boundary findings.
- **With generated sources deleted, every finding degrades to `UNRESOLVED` and nothing
  blocks.** Verified by deleting them and re-running, not by assertion.

---

## Not scheduled

TypeScript analysis (lexical, cannot block — enforced by `Finding.__post_init__`), MCP
server, container image, CrewAI/OpenAI-Agents adapters, GitHub Action, VS Code, Chrome,
Rust core. Each is a wrapper over `verify_change`; none is a prerequisite for the others.
