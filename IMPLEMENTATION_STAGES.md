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

### 9.4. Built: accessor equivalence ✅

`aegisflow/core/accessor.py` normalises a property and its accessor to one subject:
`invoice.total`, `invoice.getTotal()`, `invoice.get_total()` and `invoice.total()` all
reduce to `invoice.total`, and chains reduce throughout
(`order.getInvoice().getTotal()` → `order.invoice.total`). Covers the JVM, .NET properties,
Python `@property` and Ruby `attr_accessor` conventions with **no parser and no build**.

Two safety properties, both tested:

- **Only zero-argument calls are accessors.** `inv.get(key)` is a lookup and
  `inv.getTotal(currency)` is a computation; neither is normalised.
- **It is applied only after exact matching fails**, so it can *suppress* a false finding
  and never invent a true one. A weakening hidden behind an accessor rename
  (`inv.total == 42` → `inv.getTotal() is not None`) still fires, and a genuinely different
  subject (`inv.subtotal`) still fires.

It composes with parametrisation: `calc(1).total` and a parametrised
`calc(n).getTotal()` reduce to the same key. Enabled by default; `subjects.accessor_equivalence`
turns it off.

### 9.5. Built: assertion style is the project's choice ✅

A project writing `assert_that(x).is_equal_to(y)` must get the same verdicts as one writing
`assert x == y`. Before this, fluent assertions were **invisible**: weakening one passed
silently, and every test in such a project would eventually have been accused of asserting
nothing. Both are the failure modes this project exists to prevent, arriving through the
front door.

`recognise.py` now reads, in addition to bare `assert` and `unittest`:

| Style | Example |
|---|---|
| assertpy / AssertJ | `assert_that(inv.total).is_equal_to(42)`, `assertThat(x).isEqualTo(42)` |
| Jest | `expect(x).toBe(3)`, `expect(x).toBeDefined()` |
| Chai | `expect(x).to.equal(3)`, `expect(x).to.be.above(5)` |
| Hamcrest matchers | `assert_that(inv.tax, equal_to(0))` |

Three things make this general rather than a list of special cases:

- **Names are folded.** `is_equal_to`, `isEqualTo` and `IsEqualTo` all reduce to
  `isequalto`, so one table serves snake_case and camelCase ecosystems alike.
- **The subject comes from the chain root, the relation from its terminal.** Reading only
  the outer call name would find neither.
- **Chai splits the relation across links**, so the terminal is tried alone and then with
  each preceding link folded onto it — covering connector words (`to`, `be`, `deep`)
  without enumerating them.

Negation weakens rather than inverts: `expect(x).not_.to_be(y)` bounds the value instead of
pinning it, so it ranks `COMPARISON`, not `EQ`. An unrecognised terminal becomes `OPAQUE` —
known to be an assertion, of unknown strength — rather than disappearing.

**Migrating between styles is not a weakening**, in either direction, because both reduce
to the same subject and relation. Switching style is also not a way to smuggle a downgrade
past: `assert x == 42` → `assert_that(x).is_not_none()` still fires.

**And a style we do not read degrades rather than accuses.** Statement-level calls no
recogniser understood are recorded on the `TestCase`; if they read like assertions, the
`empty_test` rule stays silent. A genuinely empty test — `setup_database()` and nothing
else — is still caught.

### 9.6. Not yet built

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

### 9.7. AegisFlow exposes the MCP; it does not consume others

The MCP surface is worth building, inverted from the obvious direction. Its value is not
"verify this edit" — it is **resolution**:

> *"What members does `Invoice` actually have?"*
> → `getTotal(): BigDecimal — generated by Lombok @Data, from target/generated-sources/…`

That is information an agent **cannot obtain by reading the file**, which is precisely the
gap worth filling. One oracle answering from source plus the build's real output, rather
than an integration per framework. When the answer is unknown it says so: an oracle that
admits ignorance is usable, one that guesses is worse than none.

---

## Stage 10 — Refactor integrity ✅

Found by reviewing a bug made *while building this*: splitting a module carried two
functions into the wrong file and left renamed call sites behind. The suite caught it —
but only because that code had tests, and only after running them. **The tool itself was
blind to it**, because `verify_change` returned `pass` for every non-test file, and
refactors live in source.

That is a second failure class, distinct from test tampering:

| | Test tampering | Broken refactor |
|---|---|---|
| What breaks | verification gets weaker | code stops resolving |
| Still parses? | yes | yes |
| Caught by tests? | no — the tests are the thing being weakened | only if that path is covered, and only after running them |
| Caught by coverage? | no | no |

### 10.1. Two rules, both differential

`core/symbols.py` collects what a module binds, loads and exports. `core/refactor.py`
turns that into findings, **for every Python file, not only protected tests**:

- **`dangling_reference`** — a name used after the change that nothing in the module
  defines, imports, or binds. This is the rename-without-updating-call-sites bug, and it
  caught both halves of the original when reconstructed.
- **`export_removed`** — a name dropped from `__all__` and defined nowhere in the change
  set. Pooled across files, so moving a definition between modules is not a removal.

Both ignore problems that already existed: adopting this on a repository with pre-existing
dynamic tricks must not produce a wall of findings nobody caused.

### 10.2. Bindings are over-approximated on purpose

Every name bound *anywhere* in a module counts, including inside other functions. A local
in one function therefore masks a genuine problem in another. That direction is chosen
deliberately: it yields false negatives rather than false positives, and a refactor checker
that cries wolf is one nobody runs. `import *` disables the check entirely and says so —
anything could be in scope, and a confident answer is not available.

Validated against the whole real codebase: **zero dangling names across every file**, with
a test that fails if that ever stops being true.

### 10.3. It works on legacy-to-functional conversions

Converting a class to functions is exactly the shape of change this covers. A complete
conversion — including a rewrite to `reduce`-style composition — is silent; one that leaves
`InvoiceCalculator(1.2).total(...)` behind after deleting the class is caught and names the
symbol. Tests for both are in `tests/test_refactor.py`.

### 10.4. It caught the same mistake again, during its own development

Splitting `verify.py` in this stage left a stale `_OFFENCE_POLICY` block and dropped an
import. Run against that change, the rule reported `testintegrity` and `monotonicity` as
dangling with line numbers, and afterwards found a missing `Confidence` import the same
way — each time before the suite was run.

---

## Stage 11 — Maintainability and change size ✅

> *"We don't want an agent producing 5000 lines of code humans can't manage."*

Two different problems, and only the first is about code quality:

- **Reviewability** — a change so large nobody reads it line by line. Bounded by
  `change_too_large`, per file and across the whole change set.
- **Maintainability** — what the resulting code looks like. Bounded by limits on file
  length, function length, parameters, nesting, complexity, duplication and catch-all
  module names.

### 11.1. Not "SOLID enforcement"

File length, function size, parameter count, nesting, cyclomatic complexity, duplication
and utility-dump module names are all decidable from source. **Liskov substitution and
dependency inversion are not.** A tool claiming to check them would be inflating vocabulary
over substance, which RULES.md section 5 forbids — so these are named as what they are:
checkable proxies for maintainability.

### 11.2. Differential by default, absolute on greenfield

A module that was already 500 lines is not this change's fault; growing it further is. So a
violation is reported only when the change **introduced or worsened** it, and improving a
file that is still over its limit stays silent. That lets the rules be switched on in an
existing repository without a wall of findings nobody caused, while ratcheting in the right
direction.

`"greenfield": true` makes every limit absolute — the right default for a project starting
clean, which is where these standards are actually achievable.

### 11.3. Duplication is compared by shape, not text

`metrics.shape_of` fingerprints a function's AST with identifiers erased, so a copy-paste
that renamed its variables is still found. Functions under five statements are excluded:
two three-line accessors being identical is a coincidence, not duplication.

### 11.4. New rules come from config, new rule *kinds* from installed packages

Teams extend the rule set declaratively in `.aegisflow.json`:

```json
"custom": [
  {"name": "no_network_in_core", "path": "aegisflow/core/**",
   "forbid_import": "requests",
   "message": "The core must never reach the network. See RULES.md section 4."}
]
```

`forbid_call`, `forbid_import` and `require_name_pattern`, each scopable by path glob and
carrying its own severity. **Declarative on purpose:** `.aegisflow.json` is repo-committed,
so a rule that could name code to run would mean cloning a repository executes it. New rule
*instances* come from configuration; new rule *kinds* come from installed packages, which
is an explicit act.

This repository now enforces its own architecture rule this way — `aegisflow/core/**` may
not import `requests`, and the adapters are out of scope.

### 11.5. Dogfooding, reported honestly

Run in greenfield mode over AegisFlow's own source, the rules produce **21 findings**:

| Rule | Count |
|---|---|
| `complexity_too_high` | 11 |
| `function_too_long` | 5 |
| `too_many_parameters` | 5 |
| `file_too_long`, `utility_module`, `duplicate_implementation` | 0 |

The rules RULES.md actually mandates — 300-line files, no utility dumps, no duplication —
are clean, and there is a test that fails if that stops being true. The violations are in
stricter limits chosen as defaults here (50-line functions, complexity 10, 5 parameters),
which the project has not adopted. `_scan_stmt` at 21 branches is a genuine finding, not
noise.

---

## Stage 12 — Architectural boundaries ✅

Found by auditing rather than by planning: `policy.boundaries.zones` had existed since
Stage 0, this repository's own `.aegisflow.json` declared two zones, and **nothing
evaluated them**. A policy section that looks enforced and is not is precisely the defect
this project was created to prevent — it is the same shape as the `audit` command that
printed "Clean" without reading a file, which was deleted on day one.

That it survived eleven stages is worth recording: rules are easy to declare and easy to
leave unwired, and only running them against a real repository surfaces it.

### 12.1. Honest positioning

`import-linter`, `dependency-cruiser` and ArchUnit do this well and are more mature.
AegisFlow does not claim to better them. It is here because the policy already declares
zones, and because a rule an agent is **told about in the same verdict** is worth more than
one it discovers later from a separate tool failing.

### 12.2. Relative imports must resolve, or the rule is decorative

`from ..langgraph import node` compared literally matches no pattern, so a zone rule would
silently protect nothing. Imports are resolved against the file's own package —
`aegisflow/core/x.py` + `from ..langgraph import node` → `aegisflow.langgraph` — with
`__init__.py` resolving to the package it defines rather than its parent.

Patterns accept both spellings found in the wild: module paths (`app.adapters.*`,
`requests`) and file globs (`src/db/**`). A bare package name forbids everything beneath
it, and `a.b.*` also forbids importing `a.b` itself — matching only submodules would leave
the package import as a hole in a rule that looks closed.

Precision is checked in both directions: `requests` does not match `requests_mock`, and
`aegisflow.core.diff` does not match `aegisflow.core.difftool`.

### 12.3. Differential, like every other rule

A violation already present before the change is not attributed to it, so the rule can be
switched on in an existing repository without blaming inherited coupling.

### 12.4. This repository now enforces its own architecture

The two zones in `.aegisflow.json` are live: `aegisflow/core/**` may not import an adapter,
`langgraph`, or the network; `aegisflow/langgraph/**` may not reach into core internals and
must depend only on the verdict API. **Zero violations across the real source tree**, with
a test that fails if that changes — and tests that fail if the wiring is ever removed again.

---

## Stage 13 — Repository audit ✅

```sh
aegisflow scan                       # audit the working tree
aegisflow scan --rule dangling_reference --json
```

Another gap found by asking what someone does first: every existing surface verifies a
*change*, and there was no way to ask what state a repository is in before any agent has
touched it. The deleted JS CLI had an `audit` command; removing it on day one was right —
it checked nothing — but nothing replaced it.

### 13.1. Absolute, not differential — and the distinction is load-bearing

Most rules are differential so that adopting AegisFlow does not blame inherited debt on the
next edit. A scan has no "before", so every rule runs absolutely and reports everything it
finds. Structure limits are forced into `greenfield` mode for the same reason.

The output says so explicitly: **a scan reports the state of the repository, not the effect
of a change.** Confusing the two would make a clean repository look broken, or a broken one
look clean.

Assertion monotonicity cannot participate at all — it compares two states and a scan has
one. That is stated rather than silently skipped.

Results are ordered deterministically: `walk` sorts rather than taking filesystem order, so
two scans of the same tree produce byte-identical output.

### 13.2. Dogfooded

Against AegisFlow's own 37 files: **zero** findings for `dangling_reference`,
`boundary_violation`, `export_removed`, `duplicate_implementation`, `file_too_long` and
`utility_module`, with a test that fails if any of those appear. The 23 remaining findings
are all in the stricter maintainability limits chosen as defaults in Stage 11
(complexity 10, 50-line functions, 5 parameters) — real signals the project has not yet
adopted, not noise.

### 13.3. The split that proved the Stage 10 rules

`cli.py` crossed 250 lines and was split into the argument surface and the command
implementations. Running AegisFlow's own `dangling_reference` check on the result **before
the test suite** reported four missing imports in `cli.py` and a stray `main` reference in
`commands.py` — the same class of mistake as Stage 10, caught in seconds instead of by 106
failing tests.

Two further failures in that split are worth recording because the rules did **not** catch
them:

- **`EXIT_FINDINGS` stopped being re-exported.** Not a dangling reference — nothing in the
  file used it — so only the test suite found it. Fixed by giving `cli.py` an explicit
  `__all__`, which puts the shell contract under the `export_removed` rule; confirmed that
  removing it again is now caught.
- **A local parser variable named `check` shadowed the imported `check` handler**, so
  `handler=check` bound an `ArgumentParser`. Both names exist, so name-resolution analysis
  cannot see it. A shadowing rule would be a reasonable addition.

---

## Stage 14 — Integrity of the checks themselves ✅

> *"The agent made the tests pass by weakening the tests"* has a sibling one layer up:
> **the agent made CI pass by weakening CI.**

Found by asking what an agent can still do once assertions are protected. The answer is
everything in `.github/` — and AegisFlow verified none of it. Worse, it reported workflow
files as `checked`, claiming a verification it had never performed.

### 14.1. Two rules

- **`ci_check_removed`** — a job or step present before and gone after.
- **`ci_check_disabled`** — a step that can no longer fail: `continue-on-error: true`,
  `if: false`, or a command ending `|| true` / `; true`. Job-level suppression disables
  every step inside it.

Identity is the command with suppression stripped, so a step that gains `|| true` is
recognised as **the same step, disabled** — not as one step removed and a different one
added. Getting that wrong would report the most common neutering as two unrelated events.

### 14.2. Lexical, therefore incapable of blocking

CI definitions are YAML and the core takes no runtime dependencies, so this is a
line-based analysis rather than a parse. Findings carry `Confidence.LEXICAL`, which
`Finding.__post_init__` **refuses to let block** — configuring `check_disabled: "block"`
raises rather than silently gating work on a guess. There is a test asserting exactly that.

### 14.3. A bug the tests caught

The first implementation ended a step block at the next sibling `- ` only, so a step
swallowed the following job and read *that* job's `continue-on-error` as its own. Blocks
now also end on dedent. It was caught by a test asserting one finding and receiving two —
which is why rules are tested for the count they produce, not merely that they fire.

### 14.4. Scaffolding, and why these templates

`.github/` now carries a pull-request checklist derived from `RULES.md` (differential
findings, uncertainty cannot block, no claim without a benchmark, `SCHEMA_VERSION` on
verdict changes), CODEOWNERS covering the three files that decide what a verdict says,
Dependabot, a security policy, and `.pre-commit-config.yaml` running `aegisflow check
--diff -` on staged changes.

The two lead issue templates are **false positive** and **missed detection** rather than a
generic bug form, because those are the two failure modes that decide whether this project
is worth running — and the false-positive template asks for the before, the after, and why
the change was legitimate, which is exactly the corpus the rules are tuned against.

### 14.5. Also fixed: `checked` meant nothing

`verify_change` appended a path to `checked` whenever no rule had run, so an unanalysed
file looked like one that passed. `checked` now means *at least one rule evaluated this
file*; a file no rule applies to is neither checked nor skipped.

---

## Stage 15 — MCP server and open-source front door ✅

```sh
aegisflow install-mcp --list
aegisflow install-mcp --client cursor
aegisflow install-mcp --client zed --show     # print, do not write
```

The MCP server was listed as "not scheduled" through fourteen stages. It is the surface
that reaches editors AegisFlow has no other door into — Cursor, Windsurf, VS Code, Zed —
and it needs no dependency, because MCP's stdio transport *is* newline-delimited JSON-RPC.

### 15.1. MCP explains; it does not enforce

Stated in the module docstring, the README and the CLI output, because it is the thing
most likely to be misunderstood. An MCP tool is one the agent **chooses** to call, so an
agent intent on weakening a test will not ask. Its value is the other half of the problem:
a blocked agent otherwise burns tokens guessing *why*, and these tools answer
deterministically for free. Enforcement remains the hook, pre-commit, CI, and the graph
edge.

### 15.2. Two properties the tests assert

- **stdout carries protocol and nothing else.** A stray print corrupts the stream and the
  client disconnects, so every response line is parsed back as JSON in a test.
- **No single bad message ends the session.** Malformed JSON, a non-object request, an
  unknown method and a failing tool each produce an error response and the loop continues —
  asserted by feeding a broken line between two good ones and requiring three responses.

Protocol version is negotiated by echoing the client's requested revision when it looks
valid, falling back to `2024-11-05` otherwise. **Worth verifying against the current
specification before release** — this was implemented from the protocol's shape rather than
against a live client.

### 15.3. Client configuration is data, and it will drift

`mcp/clients.py` holds every path and shape: `mcpServers` for most, `servers` with
`type: stdio` for VS Code, `context_servers` with a nested command for Zed. Vendors move
these between releases, so `--show` prints the snippet for anyone who would rather wire it
by hand, and the docs say plainly that the writer may go out of date while
`aegisflow mcp` will not.

Existing configuration is backed up before it is touched — including when it is unparseable,
which is exactly when a user most wants the original back.

### 15.4. The front door

The README was a design document, not a project page. It now opens with badges, a contents
list, install instructions including `pipx` and `uv`, a three-step quick start, per-editor
MCP setup, and contributing and licence sections. `CODE_OF_CONDUCT.md` completes the
standard set.

---

## Stage 16 — adversarial review ✅

Not a planned stage. A sceptical buyer was asked to attack the product with tests rather
than opinions, and what they broke set the scope. Full write-up in
PLAN_AND_POSITIONING.md §10; the mechanics:

**16.1 `pass` on a file nothing analysed.** `Status.UNVERIFIED` (verdict `schema_version`
2), CLI exit `3`, router edge `on_unverified` defaulting to unmapped. Derived from
findings *and* coverage, and only when the whole change was unanalysable — a single
unsupported file among many stays `pass` with the gap recorded, because a status people
learn to ignore protects nobody.

Adding a status broke fail-open in two places at once: `blocks()` and `decision_json()`
each tested `status is Status.PASS` directly, so the hook would have denied every
TypeScript edit. Both now go through one definition of "let it through", and three tests
pin it. Worth noting as the general hazard: **widening an enum silently changes the
meaning of every `is not PASS` in the codebase.**

**16.2 Helper assertions invisible in both states.** `core/delegation.py` attributes a
helper's assertions to the calling test, substituting call-site arguments for parameters
and following helper-to-helper chains to a bounded depth. The helper map is grown to a
fixed point, because a function that only *calls* an asserting helper is still on the path
from the test to the assertion. Symmetric across before and after, so it cannot invent a
weakening.

**16.3 False positives, 4/12 → 0/12.** `await` stripping and single-assignment alias
resolution in `core/subject.py`; exact literal decomposition in `core/decomposition.py`.
All applied as fallbacks after exact matching, so each can suppress a finding but never
invent one. Detection re-measured after every fix and did not move.

**16.4 The missing measurement.** `tests/corpus/` — 19 legitimate refactors, 18 tampering
patterns, split by provenance so cases used while fixing the checker are reported
separately from cases written afterwards. `python -m tests.corpus` prints the rate;
`tests/test_corpus.py` makes it a CI gate.

**Gate.** 520 tests pass. Corpus: 0 false positives, 0 false negatives on both splits.
Self-audit went 27 findings → 24 — three removed, none added, and `compare`/`_lookup` were
refactored rather than exempted.

**Method worth keeping.** Every gap here came from running the tool against cases it had
not been built for, not from reading the plan. The two that mattered were both invisible
to the test suite: 520 passing tests coexisted with `pass` on unanalysed files and a blind
spot covering any suite that uses assertion helpers.

---

## Stage 17 — removing the friction ✅

The objection that decides adoption turned out not to be about the checks at all. Setup
was three commands, every entry point demanded that the caller describe the change, and
two of the registered commands could fail silently.

**17.1 `aegisflow review`.** The zero-argument entry point: it reads the uncommitted diff
from git and verifies it. Every other surface asks *what changed*; the person running this
has already made the change and wants to know what it broke. Exposed over MCP as
`aegis_review`, the tool an agent calls after finishing a set of edits.

Running git is a **surface** concern, not a check — the same shape as the existing
`git diff | aegisflow check --diff -`. The verdict is still computed by the pure engine
from the diff text, so RULES.md §4 holds: given the diff, the answer does not depend on
git being present.

One bug found by its own test: `git diff` omits untracked files, and emptiness was judged
before they were added, so a change consisting only of **new files** reported "nothing to
check" — the most interesting thing an agent produces was the one case not checked.

**17.2 `aegisflow init`.** Config, MCP registration and hook in one idempotent command.
Advisory by default, because a gate that blocks on its first run in an unfamiliar
repository gets uninstalled rather than tuned. Three separate commands was three chances
to stop halfway, and the half usually skipped was the hook — the only one that enforces.

**17.3 Commands that actually resolve.** Both the MCP server and the hook were registered
as a bare `aegisflow`. When that is not on the client's PATH — conda, virtualenvs, an
editor launched from a desktop icon — the failure surfaces as *"server failed to start"*
rather than *"not on PATH"*. Now resolved at install time: the bare console-script name
when it exists, since `.mcp.json` is committed and an absolute path works on one machine,
falling back to `<interpreter> -m aegisflow`, which cannot fail to resolve. That fallback
needed `aegisflow/__main__.py`, which did not exist.

**17.4 Instructions over MCP.** The server sends MCP `instructions` naming when to call
each tool. MCP still explains rather than enforces — an agent that does not want a verdict
will not ask — but the gap between "the tool exists" and "the agent knows to use it" was
free to close.

**Gate.** 541 tests. Corpus unchanged at 0 false positives and 0 false negatives. Self-audit
unchanged at 24 findings — four new modules, none of them adding one. Verified by running
the registered command as a real subprocess over stdio, not by calling the handler
in-process: initialize, tools/list and a tools/call all answered, stdout clean.

---

## Stage 18 — making the value checkable ✅

"Zero-token deterministic critique" was true by construction and invisible in practice,
which makes it indistinguishable from a slogan. `ledger.py` appends one line per verdict;
`stats.py` reports it.

**The design constraint is the tiering.** Three kinds of number, never blended:

- *Measured* — verdicts, findings by rule, prescription characters, source characters
  analysed, elapsed milliseconds.
- *Architectural* — AegisFlow makes zero model calls, so an LLM-as-judge doing the same
  job costs one per verdict. A property of how each is built, not an observation.
- *Estimated* — tokens as characters over a stated constant, labelled everywhere it
  appears, because pinning a real tokenizer would mean a dependency and a false precision.

And one heading for what is **not** claimed: fewer total model calls to convergence
remains unbenchmarked (§4.1), so the report says so rather than omitting it silently.

**Prompt compaction, honestly.** Reported as analysed characters per prescription
character. The first end-to-end run printed "critique is 0x smaller", because on a small
change the prescription is legitimately *larger* than the code — the ratio is now stated
in whichever direction is true rather than rounded into a nonsense win.

**Constraints held.** Recording happens after a verdict exists and cannot alter one;
`observe()` is pure and the clock is read only at the surface, so RULES.md §4 still holds
for everything in `core`. A failed write is swallowed — bookkeeping must never fail a
verification. Local only, no network. The ledger directory writes its own `.gitignore`
rather than editing one the project owns.

**Gate.** 558 tests. Corpus unchanged at 0/0. Self-audit 24 → **23**: two new modules,
neither adding a finding, and the CLI parser split removed one. Proved end to end with the
installed binary — hook blocks a weakening, `aegisflow stats` shows it.

---

## Stage 19 — fan-out, long sessions, and integration examples ✅

The question was whether this survives the way agents are actually run: hundreds of
workers on one repository, for hours. Three defects, each found by measuring rather than
reasoning.

**19.1 The per-turn total was quadratic.** Adding the footer in Stage 18 made every verdict
re-read and re-summarise the whole ledger — O(events) per call, O(events²) over a session.
Measured at 680 ms per verdict with 20,000 events. Now folded incrementally from a cached
byte offset in `totals.py`: flat at ~1 ms at any size, with the cache distrusted on read so
a stale or rotated one costs a full read rather than a wrong answer.

**19.2 Ledger writes were unsafe under a fan-out.** The old trim read the file and wrote it
back, discarding concurrent appends. Now one atomic append per event, capped below the
POSIX atomic-write size, with rotation as an atomic rename behind an exclusive lock.
Pinned by 12 real processes writing concurrently.

**19.3 Isolated verification is wrong for a fan-out.** A test moved from worker A's file to
worker B's reads as a deletion to A and a no-op to B. Both wrong, and neither worker can
see it. `also_covered` already existed; `examples/langgraph_fanout.py` shows the same edits
scored both ways and is asserted on in `tests/test_examples.py`.

**Also.** Per-agent attribution through `AEGISFLOW_RUN_ID`/`AEGISFLOW_AGENT`; source-level
acknowledgements (`# aegisflow: allow <rule> - <reason>`, one rule, reason required,
counted in stats) so an intentional change is answerable without switching the rule off;
`UNVERIFIED` exported from the LangGraph package, which it never was.

**Ten examples**, from LangGraph to a thirty-line plain loop, with `tests/test_examples.py`
running the standalone ones and checking that the framework ones import lazily.

**Gate.** 581 tests. Corpus unchanged at 0/0. Self-audit 23 — six new modules across two
stages, none adding a finding.

**Worth keeping.** Every defect in this stage came from measuring the thing under load, not
from reading the code. The quadratic footer was written, reviewed and tested three stages
in a row without anyone noticing, because at twenty events it is free.

---

## Not scheduled

TypeScript analysis (lexical, cannot block — enforced by `Finding.__post_init__`), MCP
server, container image, CrewAI/OpenAI-Agents adapters, GitHub Action, VS Code, Chrome,
Rust core. Each is a wrapper over `verify_change`; none is a prerequisite for the others.
