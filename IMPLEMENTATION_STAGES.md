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

## Stage 8 — Voice ✅

`Verdict.speak()`, confirmation tokens, mode-dependent severity. See section 9.

**Gate:** a verdict renders as one spoken sentence, and a high-blast-radius change requires
explicit assent before apply. ✅

```sh
aegisflow check --path tests/test_invoice.py --before old.py --after new.py --speak
```

Implemented in `aegisflow/speech.py` as a free function rather than the `Verdict.speak()`
method section 9.6 sketched: rendering for a listener is a separate responsibility from the
verdict contract (RULES.md section 2), and a method would have made `verdict.py` import the
speech layer that imports it back.

Two problems shaped it, neither of them text-to-speech:

- **A verdict must survive being heard.** `tests/test_invoice.py:41` is noise aloud, so
  speech uses names, not paths, and one sentence before any detail. Details quote each
  finding's own subject — two findings from one rule usually concern different subjects,
  and hearing the same sentence twice tells the listener nothing. Screen notation
  (`->`, `non_null`) is spoken as words.
- **Assent must survive being misheard.** Listening for "yes" is unsafe: recognisers
  mistake short words and background conversation contains them. A risky change asks for a
  specific uncommon word, derived deterministically from the change itself — same change,
  same word; no randomness (RULES.md section 4). `matches()` tolerates casing, punctuation
  and filler, and rejects "yes", "sure" and "go ahead".

**Mode-dependent severity composes with it.** `Policy.for_voice()` raises every rule to a
configurable floor, defaulting to `escalate`: a `repair` finding is fine on a screen because
the human sees the diff regardless, but spoken, nobody sees anything. A weakened assertion
is `repair` on screen and `escalate` aloud — which then triggers the spoken checkpoint.

---

## Stage 9 — Generated code, in every language

An earlier draft framed this as a Java problem about Lombok and MapStruct. That was too
narrow. **The source text is not the program** in every ecosystem, and the two named tools
are one instance of a phenomenon with many.

### 9.1. It is not N frameworks — it is five mechanisms

Enumerating tools is an unbounded treadmill. Enumerating *mechanisms* is not, and each one
has a different detection strategy and a different consequence.

| # | Mechanism | Examples | Artifact on disk? | Strategy |
|---|---|---|---|---|
| 1 | **Ahead-of-time codegen** | Lombok, MapStruct, Dagger, protobuf, Prisma, GraphQL codegen, `go generate`, bindgen, OpenAPI | **Yes** — real source | Read it, and never analyse it as authored ✅ **built** |
| 2 | **Compile-time expansion** | Rust proc macros, C++ templates and the preprocessor, Scala macros, Vue/Svelte compiler macros | No | `cargo expand`, `gcc -E`; else degrade |
| 3 | **Runtime metaprogramming** | Python `__getattr__`, pydantic, SQLAlchemy, Django ORM, Ruby `method_missing`, ActiveRecord | No — nothing exists until import | Cannot resolve statically; degrade, or use type stubs |
| 4 | **Type-level only** | TS mapped and conditional types, `.d.ts`, tRPC inference | Types only | Low impact: tests call members, not types |
| 5 | **Call-time injection** | pytest fixtures, Spring, Dagger, DI containers | No | Low impact: the subject expression still stands |

### 9.2. Most of this does not affect the core check, and that is by design

Assertion monotonicity compares subject *expressions*. `invoice.getTotal()` is matched
against the other side as written; the engine never resolves what the method is or where it
came from. Mechanisms 2 through 5 are therefore largely invisible to it.

That is not luck. Comparing rather than resolving is what makes the check robust to code
generation, and it should be preserved deliberately as more languages are added.

Where generation genuinely bites:

- **Field ↔ accessor refactors** — `invoice.total` → `invoice.getTotal()` reads as one
  subject lost and another gained. Same class as the subject-aliasing limitation already
  pinned in `tests/test_monotonicity.py`. Affects Java, C# properties, Python `@property`,
  Ruby `attr_accessor`.
- **Anything resolution-based** — boundary and import rules, where `InvoiceMapperImpl`
  exists only in generated output.
- **Analysing generated output as authored** — the dangerous one, addressed below.

### 9.3. Built: language-general detection ✅

`aegisflow/core/generated.py` detects generated files with **no parser and no build**,
because generated files announce themselves. Two signals:

- **Header markers**, and the conventions are shared across ecosystems: Go specifies
  `// Code generated ... DO NOT EDIT.`, .NET emits `<auto-generated/>`, and the bare
  `@generated` tag is common. Checked only in the first 15 lines.
- **Paths**: build output and codegen conventions across JVM, protobuf, Go, TS/JS, .NET,
  Dart and Kubernetes. Extendable per project via `generated.extra_patterns`.

**Detection is biased toward "authored" on purpose.** Calling authored code generated
silently skips verification of a real test file — the exact hole this project exists to
close. Calling generated code authored merely wastes a check. So a bare `DO NOT EDIT` is
*not* sufficient (`// do not edit without asking Priya` is a human comment on human code),
and `generated by …` must open a comment line rather than appear in prose
(`# the id is generated by the database`). Both cases are pinned as tests.

Two consequences, both language-general:

1. **Generated files are never verified as authored source.** Nobody wrote their
   assertions and their style is not a person's choice. They are recorded in `skipped`,
   never in `checked`.
2. **Hand-editing generated output is itself a finding.** The next build discards the edit,
   so the fix belongs in the source or the generator configuration.

The second needed a distinction worth keeping: **regenerating is normal, hand-editing is
not.** `verify_change(..., hand_edit=True)` is passed by the hook, which sees an edit being
composed; the diff path leaves it off, so committed regenerated output stays silent.

### 9.4. Not yet built

- **Accessor equivalence** — normalise `x.total` / `x.getTotal()` / `x.isTotal()` to one
  subject. Removes the field↔accessor false positive with no parser and no build
  dependency. Highest value per line remaining in this stage.
- **Reading generated sources** for resolution-based rules (mechanism 1), from
  `target/generated-sources/**` and `build/generated/**`. One integration covers every
  annotation processor, because they all write there. Ask the build, not the framework.
- **Staleness handling.** Generated sources exist only after a build; inside an agent loop
  they are often absent or stale. Present and fresh → `Confidence.EXACT`; otherwise
  `Confidence.UNRESOLVED`, which **cannot block** — enforced in `Finding.__post_init__`,
  not by convention.
- **Per-language parsers.** Java, TypeScript and the rest need a parser dependency, which
  breaks the core's zero-runtime-dependency property. That is a deliberate decision to make
  when a language is scheduled, not to drift into.

### 9.5. AegisFlow exposes the MCP; it does not consume others

The MCP surface is worth building, inverted from the obvious direction. Its value is not
"verify this edit" — it is **resolution**:

> *"What members does `Invoice` actually have?"*
> → `getTotal(): BigDecimal — generated by Lombok @Data, from target/generated-sources/…`

That is information an agent **cannot obtain by reading the file**, which is precisely the
gap worth filling. One oracle answering from source plus the build's real output, rather
than an integration per framework. When the answer is unknown it says so: an oracle that
admits ignorance is usable, one that guesses is worse than none.

---

## Not scheduled

TypeScript analysis (lexical, cannot block — enforced by `Finding.__post_init__`), MCP
server, container image, CrewAI/OpenAI-Agents adapters, GitHub Action, VS Code, Chrome,
Rust core. Each is a wrapper over `verify_change`; none is a prerequisite for the others.
