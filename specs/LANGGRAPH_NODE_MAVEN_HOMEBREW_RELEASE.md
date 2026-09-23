# Cross-language LangGraph release implementation specification

**Status:** implementation complete and release-verified locally. Publication
is intentionally gated on registry ownership, Maven Central credentials/signing
key, and a Homebrew tap token; these are external account actions, not code
that can safely be created from this repository.

**Implementation progress:** 7/7 stages implemented. The complete release
preflight passes the Python suite, Node real-CLI/LangGraph and packed-consumer
tests, Java real-CLI/LangGraph and clean-consumer tests, artifact builds, and a
clean-room Python installation. A stage is only marked complete after its tests
pass and its work is reviewed against this specification.

1. Shared contract fixtures and Python fixture tests.
2. Node SDK, real CLI/graph integration tests, and packaged-consumer smoke test.
3. Java/LangGraph4j SDK, real graph tests, and packaged-consumer smoke test.
4. Version synchronization and release preflight across all artifacts.
5. Release workflow: GitHub assets, npm provenance, Maven Central publishing.
6. Verified Homebrew formula and release updater.
7. GitHub Pages/API reference, runnable examples, hook/CI integration docs.

### Release activation checklist (external setup)

Before triggering the first non-draft release, a maintainer must complete the
account-bound configuration documented in `RELEASING.md`: claim the npm scope,
verify the Maven Central namespace and configure its signing key/secrets, and
create `tensilestream/homebrew-tap` with a contents-write token. The workflow
contains the publish/update jobs but deliberately cannot fabricate these
identities or credentials.

**Goal.** Ship Yieldpoint's existing verification gate to JavaScript and Java
agent graphs, and release it from the same `vMAJOR.MINOR.PATCH` tag as the
Python package. The release must also provide a verified Homebrew install for
the CLI.

The feature is a binding, not a second verifier. Python remains the sole
implementation of rules and verdict construction. The JavaScript and Java
packages invoke a pinned `yieldpoint` CLI with fixed argument arrays, parse the
versioned verdict JSON, and express its result as a graph-state update plus a
route. This preserves the product's “a missing analysis is not a pass” rule.

## Canonical-engine rule: no duplicated verifier

There must be exactly one implementation of Yieldpoint rules: the Python core
under `yieldpoint/core/`, reached through `yieldpoint.verify`. Node and Java
are **adapters**. They are not ports of `verify_change`, `verify_diff`, policy
loading, AST parsing, rule selection, severity calculation, or verdict
construction.

```text
             Python package / Homebrew install
                         │
                         ▼
  policy + change ──> yieldpoint check --json ──> schema-versioned Verdict JSON
                                                        │
                       ┌────────────────────────────────┴───────────────┐
                       ▼                                                ▼
        @tensilestream/yieldpoint-langgraph       yieldpoint-langgraph4j
              Node process + state adapter          Java ProcessBuilder + state adapter
                       │                                                │
                       ▼                                                ▼
                LangGraph.js node/route                     LangGraph4j node/route
```

This is possible today because the CLI already accepts `check` inputs and emits
the explicitly versioned JSON contract with `--json`. The process boundary is
intentional: it means a rule fix or a new supported language ships once in the
Python wheel/Homebrew package and is immediately used by both bindings after
their installed executable is updated.

The trade-off is deliberate: Node and Java consumers need a compatible
`yieldpoint` executable available locally (or must explicitly configure its
path). The adapters must detect and explain its absence; they must never fall
back to a reduced local implementation and label the change `pass`.

### Allowed and forbidden binding logic

| Binding may own | Binding must not own |
| --- | --- |
| Finding the executable; passing fixed CLI arguments/stdin; timeout and temporary-file lifecycle; JSON deserialization; graph-state mapping; route and loop-budget mapping; typed SDK errors. | Rule identifiers; AST or TypeScript parsing; policy interpretation; finding/severity/confidence logic; supported-language decisions; `Verdict` creation/merging; any “equivalent” check implemented in TypeScript or Java. |

`Verdict` parsing models may mirror the JSON fields for type safety, but they
are read-only transport types. They must preserve unknown fields so a newer
Python producer cannot silently lose information in an older binding. A schema
version newer than the binding's supported range must fail closed as an adapter
compatibility error, never be treated as a clean result.

### Enforcing the boundary

Add these requirements to the implementation and review checks:

1. Store the same fixture requests once under `tests/fixtures/` and generate
   expected JSON only by running the Python core. Node and Java tests compare
   their adapter output byte-for-byte/structurally to those fixtures; they do
   not hand-author parallel expected findings.
2. In process-level tests, run Node and Java against a fixture `yieldpoint`
   executable that records argv/stdin and returns canonical verdict JSON. This
   proves they are clients rather than hidden rule engines.
3. Add a CI guard that rejects rule/policy/parser imports or copied rule IDs in
   `sdk/node` and `sdk/java`, apart from the closed public status constants and
   documented JSON field names. Keep the guard narrow and allow documented
   fixtures/readmes.
4. For every Python rule or verdict-schema change, update only Python rule tests
   and shared contract fixtures. Binding changes are required only when the
   public JSON schema or node-state contract changes.
5. Publish compatibility ranges: each binding documents the Yieldpoint schema
   versions it accepts, and its CI runs against the oldest and newest supported
   Python package versions.

## Re-review findings and constraints

This specification was rechecked against the repository and the BuildAnchor
reference implementation.

| Concern | Yieldpoint today | Consequence for this work |
| --- | --- | --- |
| Release pipeline | `.github/workflows/release.yml` validates/builds/releases/PyPI-publishes only. | Add npm, Maven, and Homebrew work; do not assume a generic build job publishes them. |
| Version source | `pyproject.toml` and `yieldpoint/__init__.py` are the two checked markers. | Extend the version checker and bump script before adding packages. |
| Cross-language contract | `Verdict.to_json()` is explicitly the versioned cross-language API; current schema is `4`. | Bindings parse this JSON; any incompatible change requires a schema bump and fixtures. |
| CLI boundary | `yieldpoint check` accepts file/diff inputs and `--json`; its verdict exits non-zero for a domain outcome. | Adapters must parse stdout before interpreting the process exit code. A `repair` or `block` verdict is successful adapter execution. |
| Python LangGraph binding | `yieldpoint.langgraph` implements node state, loop detection, and routing without importing LangGraph. | Preserve the exact state keys, default limits, and routing semantics in both new packages. |
| BuildAnchor reference | It validates Java and Node, publishes npm, and updates a formula. It has no Maven-Central deployment job. | Use its npm/formula conventions selectively; Maven publishing needs a new, real Central release design. |

### Decisions required before coding

The implementation should stop at these decisions if they have not been
confirmed; publishing under a guessed registry identity is not reversible.

1. Claim/confirm `@tensilestream/yieldpoint-langgraph` in npm and
   `io.github.tensilestream:yieldpoint-langgraph4j` in the Maven Central Portal.
   The names are the proposed defaults used below.
2. Use **LangGraph.js** (`@langchain/langgraph`) for Node and **LangGraph4j**
   (`org.bsc.langgraph4j:langgraph4j-core`) for Java. They are separate
   ecosystems, so “LangGraph compatible” must mean equivalence of Yieldpoint's
   state and route contract, not binary/API compatibility between them.
3. Decide whether the formula belongs in this repository or in a public
   `homebrew-tap`. A formula in this repository is installable with a full URL;
   a tap is required for a stable `brew install tensilestream/tap/yieldpoint`
   experience. The plan below starts in-repository and isolates the updater so
   it can be switched to a tap.
4. Create the Maven Central namespace, release environment, signing key, and
   npm trusted publisher before enabling the corresponding publish jobs.

## Public compatibility contract

### Inputs

Both bindings expose a `verifyNode` factory. Its default state reader accepts
the same forms as `yieldpoint.langgraph.read_change`:

```text
diff or yieldpoint_diff: unified diff string; root is optional
changes or yieldpoint_changes: [{path, before, after}, ...]
```

The Node binding may write the diff to its spawned process stdin and call:

```text
yieldpoint check --diff - --root <root> --policy <policy> --json
```

For a single file transition it must use temporary files in an OS-safe temporary
directory and call `yieldpoint check --path <path> --before <file> --after <file>
--root <root> --policy <policy> --json`. No value may be passed through a shell.
The Java binding uses the same invocation shapes through `ProcessBuilder`.

The package API must expose an explicit executable path, working root, policy,
and timeout. Defaults are `yieldpoint`, `.`, discovered policy, and a documented
bounded timeout. It must not install Python or contact a network endpoint.

### Outputs

On a parsed verdict, return exactly these default additions to graph state:

```text
verdict:                  Verdict JSON object, unchanged
prescription:             deterministic remediation string
yieldpoint_history:       bounded list of signatures
yieldpoint_attempts:      incremented integer
yieldpoint_loop_tripped:  boolean
```

Use the existing defaults: history window `6`, trip when the same
proposal/verdict signature occurs `3` times, and repair budget `3`.

Routes are the closed set `pass`, `unverified`, `repair`, `escalate`, and
`block`. `unverified` must default to its own branch rather than `pass`.
`repair` becomes `escalate` when the repair budget is exhausted or the loop
signature trips. Make the unverified/exhausted/stalled destinations explicit
adapter options, mirroring Python's `make_router`.

### Errors

Differentiate these cases in exported error types/classes:

- executable missing, timeout, or process-launch failure;
- stdout cannot be parsed as a valid schema-4 Verdict;
- CLI operational failure (no parseable verdict); and
- a valid domain verdict whose status is `repair`, `escalate`, or `block`.

Only the first three are adapter errors. The final case returns a normal node
update and must never be discarded merely because the CLI exit code is `1`.

## Repository changes

### 1. Shared conformance fixtures

Add `tests/fixtures/langgraph_contract/` with JSON state inputs and expected
state updates/routes for:

- clean evaluated change → `pass`;
- unsupported/unanalysed change → `unverified`;
- repairable finding → `repair` with prescription;
- blocking finding → `block`;
- no supplied change → `unverified` and its skip reason;
- repeated identical repair proposal → loop trip and escalation; and
- repair-attempt limit → escalation.

Add Python tests alongside the existing LangGraph tests to execute the fixtures
against `verify_node`, `make_router`, and `repair_context`. These fixtures are
the reviewable specification consumed by Node and Java tests; do not duplicate
expected verdict literals independently in each SDK.

### 2. Node package: `sdk/node/`

Create this file layout:

```text
sdk/node/
  package.json
  README.md
  LICENSE
  tsconfig.json
  src/index.ts
  src/cli.ts
  src/verdict.ts
  src/node.ts
  src/router.ts
  test/*.test.ts
```

`package.json` must be ESM, publish only compiled `dist/`, declarations,
README, and LICENSE, and expose subpaths only where deliberately supported.
Use an npm `prepack` build, `npm test`, `npm run typecheck`, and `npm pack
--dry-run` in CI. Set `@langchain/langgraph` as a peer dependency (and dev
dependency for tests), rather than forcing it into projects that only want the
CLI adapter. Pin the supported peer range after testing it; do not use `*`.

Implement these exports:

```ts
verifyNode(options?): (state) => Promise<Partial<State>>
routeOnVerdict(state): YieldpointRoute
makeRouter(options?): (state) => YieldpointRoute
repairContext(state): string
verdictFrom(state): Verdict
```

The test suite must include an actual `StateGraph` with a generator → verifier
→ conditional-edge flow, a mocked CLI-process unit suite, and a process-level
integration suite against the locally built Python project. Also install the
packed tarball in a temporary Node consumer project and run its graph test;
source-tree imports do not prove an npm release works.

### 3. Java package: `sdk/java/`

Create a standard Maven module:

```text
sdk/java/
  pom.xml
  src/main/java/io/github/tensilestream/yieldpoint/langgraph4j/*.java
  src/test/java/io/github/tensilestream/yieldpoint/langgraph4j/*.java
  README.md
  LICENSE
```

Publish `io.github.tensilestream:yieldpoint-langgraph4j`. Keep Java 17 as the
minimum because the proposed graph library and BuildAnchor's Java SDK baseline
both require it. Add a `langgraph4j.version` property and compile/test against
a deliberately pinned version; avoid version ranges in release artifacts.

Provide immutable typed models for verdicts and state updates, a
`YieldpointVerifier` for direct CLI use, a `YieldpointVerificationNode` suitable
for a LangGraph4j async node action, and `YieldpointRouter`. Isolate
LangGraph4j-specific types in the node/graph bridge so direct CLI consumers do
not require graph construction. The command runner uses `ProcessBuilder`,
merged/captured process streams only when necessary, UTF-8 JSON parsing, an
executor-based timeout, and guaranteed temporary-file cleanup.

Configure Maven Central-ready metadata: project URL, Apache/BUSL license text
that accurately matches the repository's release policy, developers,
organization, SCM connection/developerConnection, UTF-8 encoding, source jar,
javadoc jar, and a `release` profile that signs every deployable artifact.
Use the Central Publishing Maven Plugin (not a legacy OSSRH staging endpoint)
in a CI-only publish job.

The Java tests must run the shared fixture cases and a real LangGraph4j graph.
Add a clean Maven-consumer smoke test that resolves the locally installed
artifact, executes a graph, and confirms the packaged JAR—not test classes—is
used.

### 4. Homebrew formula: `Formula/yieldpoint.rb`

Add a formula that installs the release source distribution or immutable GitHub
tag archive, declares `depends_on "python"`, and exposes both `yieldpoint` and
`yp`. Include the exact `sha256`; Homebrew installations must not rely on an
unverified URL. The formula test runs `yieldpoint --version`, `yp --version`,
and one minimal JSON check.

Add `scripts/update_homebrew_formula.py` instead of release-workflow `sed`.
It must receive the resolved tag, release version, and expected archive digest;
parse and update only the intended URL/version/sha lines; fail if a marker is
missing or multiple markers match; and leave no backup file. Unit-test it with
fixture formulae. This prevents silent formula corruption and makes a future
tap migration a destination change rather than a workflow rewrite.

### 5. Versioning and preflight

Extend `scripts/bump_version.py` with explicit version sites for Node and
Maven. Its `--check` output must list each development artifact and fail when
any diverges. The Homebrew formula intentionally tracks the last published tag
and is verified by its archive URL/digest updater instead; it must not be
advanced to an unreleased development version. The bump script must not run
`npm install`, `mvn`, publish commands, or a network operation.

Extend `scripts/release-check.sh` in this order:

1. `scripts/bump_version.py --check` and changelog/version validation;
2. Python suite and existing clean-room wheel/CLI verification;
3. Node install from the lockfile, typecheck, tests, and `npm pack --dry-run`;
4. Java `mvn -B verify` including source/javadoc/signing-independent checks;
5. formula syntax/audit test and updater unit tests; and
6. a summary of exact artifact versions and expected npm/Maven coordinates.

The normal PR CI should run Node and Java package tests independently of the
full Python operating-system matrix. The release validate job repeats the
release-specific package checks on the toolchain versions that will publish.

## Release workflow design

Modify `.github/workflows/release.yml` without changing its existing tag and
draft semantics.

### Validate and build

- Install Python 3.12, Node 22, Java 17, and Maven in `validate`.
- Fail before building if Python, Node, Java, and formula versions do not equal
  the resolved `vX.Y.Z` tag.
- Build the Python wheel/sdist, run `npm pack` to create a real `.tgz`, and run
  `mvn -B package` to create binary/source/javadoc JARs.
- Upload three distinct artifacts: `yieldpoint-pypi-packages`,
  `yieldpoint-npm-package`, and `yieldpoint-maven-packages`; include a
  `SHA256SUMS.txt` manifest in the GitHub-release asset bundle.
- Have the GitHub Release job attach every user-consumable archive and only
  update the formula after a non-draft release is created.

### Publish jobs

Create independent jobs, each requiring `build` and `github-release`, each
skipped for dry runs and drafts:

| Job | Authentication | Required verification before publish |
| --- | --- | --- |
| `publish-pypi` | Existing PyPI trusted publishing/token fallback | wheel/sdist artifact downloaded by exact name |
| `publish-npm` | npm trusted publishing, `id-token: write`, npm version supported by trusted publishing | tarball version/name match the release output; `npm publish --provenance --access public` |
| `publish-maven` | `MAVEN_CENTRAL_TOKEN`, GPG private key/passphrase stored in a protected `maven-central` environment | signed source/javadoc/binary artifacts, `mvn -Prelease verify`, coordinates/version equal output |

Do not let npm or Maven rebuild from a fresh checkout after validation. Publish
the artifacts created by `build`, so the release assets, checksums, and
registries all describe the same bytes. If Maven Central requires publishing a
fresh signed bundle, rebuild only within the signed publish job after comparing
the unsigned artifact checksums and recording why; prefer producing signatures
in the central build job with protected credentials instead.

`post-release` must need all three publication jobs. Only then bump the next
patch version across every marker and commit it. A partial release must remain
visible as a failed workflow for operator remediation; it must not advance
`main` to a version that was not fully published.

### Homebrew update

After the immutable GitHub release exists, download the exact source archive,
calculate its SHA-256, execute `scripts/update_homebrew_formula.py`, run the
formula tests, and commit only the formula update. Handle a protected `main`
branch explicitly: either use a bot PR or grant the workflow a permitted path.
Do not emulate BuildAnchor's unverified `sed` replacement.

## Documentation, API reference, and integration examples

Documentation is a release deliverable, not a post-release follow-up. The
repository has two documentation surfaces that must stay aligned:

- **GitHub-facing documentation:** `README.md`, `RELEASING.md`, package
  READMEs, committed examples, and Markdown API guides; and
- **published GitHub Pages:** generated from `scripts/docs_content.py` by
  `scripts/build_docs.py`, committed under `docs/`. Do not hand-edit generated
  `docs/*.html`; change the generator content and regenerate the site.

### Documentation structure to add

Add these authored sources and link each one from the root README, the Pages
navigation, and the relevant package README:

```text
docs/sdk/node.md                    # Node installation, API, state contract, errors
docs/sdk/java.md                    # Maven installation, API, state contract, errors
docs/cli.md                         # CLI/JSON contract, exit codes, automation safety
docs/integrations.md                # developer choice guide, copied into Pages source
examples/node/langgraph_repair_loop.mjs
examples/node/package.json
examples/java/langgraph4j/pom.xml
examples/java/langgraph4j/src/main/java/.../RepairLoop.java
examples/cli/check-diff.sh
examples/cli/pre-commit-config.yaml
examples/github_action.yml          # update existing example, do not create a duplicate
```

If the Pages site continues using generated HTML, add an `sdk`/`api` page to
`PAGES`, `TITLES`, and `DESCRIPTIONS` in `scripts/build_docs.py`, then add its
content in `scripts/docs_content.py`. That page is the stable landing page for
Node, Java, CLI, hook, and Python links. Generate and commit its HTML, sitemap,
and navigation updates through `scripts/build_docs.py`.

### API documentation

Publish APIs from source, rather than maintaining signatures in prose only:

- **Node:** configure TypeDoc (or an equivalent source-driven generator) for
  public exports only. Publish the generated output to `docs/api/node/` during
  the documentation build and link it from npm's README and the Pages API
  landing page. Document `verifyNode`, `makeRouter`, `routeOnVerdict`,
  `repairContext`, options, state keys, JSON schema support, route values, and
  every error class.
- **Java:** configure `maven-javadoc-plugin` for public types and publish its
  generated output to `docs/api/java/`. The same plugin produces the Javadoc
  JAR required for Maven Central. Link it from the Maven README and Pages.
- **CLI/Python:** document the authoritative `yieldpoint check --json` input
  forms, JSON `schema_version`, full exit-code table, and the rule that valid
  JSON must be parsed even when the command exits `1`. Reference Python's
  existing `yieldpoint.langgraph` API rather than creating a second API model.

The CI documentation check must generate Node TypeDoc, Java Javadocs, and the
Pages site from a clean checkout; fail on uncommitted generated output or a
broken internal link. Package publishing and Pages publishing must use the same
commit/tag so examples cannot describe APIs that have not shipped.

### Required runnable examples

Every example must have a short “run from a blank checkout” command, expected
output, and a CI smoke test. Keep examples deterministic—use scripted changes,
not an API-key-backed LLM.

| Surface | Example must demonstrate |
| --- | --- |
| Python LangGraph | Existing `examples/langgraph_repair_loop.py`, updated only if the shared state contract changes; generate → verify → conditional route, including explicit `unverified` handling. |
| Node / LangGraph.js | Install `yieldpoint` plus the npm package; configure the executable; execute a `StateGraph`; show a failed repair followed by a pass and a separate unverified route. |
| Java / LangGraph4j | A self-contained Maven example using the published artifact and a locally configured executable; execute the equivalent graph and print verdict status/route. |
| CLI | `yieldpoint check --diff - --json`, parse the JSON without treating exit `1` as a transport failure, and a CI-ready shell example that rejects `unverified`. |
| GitHub Actions | Pin a released version, install the CLI, diff the PR base to `HEAD`, emit a useful JSON/SARIF artifact, and fail the job for findings or unverified analysis. |
| Homebrew | `brew install`/formula URL command, `yieldpoint --version`, and a minimal `check --json` verification. |

Use one common scenario (`before`, weakening, repaired change) and the shared
contract fixtures across Python, Node, Java, and CLI examples. That makes the
same outcome visibly comparable and prevents tutorial-specific rule logic.

### Developer hook and integration guide

The integration guide must help developers choose a gate based on where a
change can bypass it. Include this matrix and copyable snippets for every row:

| Option | Installation/configuration | Enforcement point | Limits to state plainly |
| --- | --- | --- | --- |
| Native Git pre-commit gate | `yieldpoint init --no-hook` or the documented Git installer | Every local commit | Does not protect changes never committed; bypass flags remain a user choice. |
| `pre-commit` framework | `.pre-commit-config.yaml` pinned to `vX.Y.Z` | Team-standard local commit hook | Must use staged-review semantics; hooks receive no unified diff on stdin. |
| CI / GitHub Action | Repository workflow using `check --diff - --json` | Pull request/merge gate | It is later than local feedback and needs correct base-ref checkout depth. |
| Claude/editor hooks | `yieldpoint init` and `install-hook [--advisory]` | Before supported edit-tool writes and/or end of turn | Tool-specific; shell/direct filesystem writes need the Git/CI backstop. |
| LangGraph Python/Node/Java nodes | Add verifier between generation and apply plus a conditional router | Before a graph applies the candidate change | Only protects paths that traverse the node; map `unverified` deliberately. |
| MCP | `yieldpoint install-mcp --client …` | Agent-requested guidance | Advisory only; it cannot enforce because the agent may not call it. |

Document a recommended layered setup: advisory editor feedback during work,
LangGraph node before application where the agent uses a graph, native/pre-
commit gate before commit, and CI before merge. State exactly which mechanisms
are advisory versus blocking, how to select advisory/enforced hook mode, and
how to troubleshoot missing executable/policy/unsupported-language outcomes.

### Documentation tests and ownership

- Extend `tests/test_docs.py` to assert the new README/API/integration links,
  generated pages, code snippets, and package coordinates are present and use
  the current version rather than an old hard-coded release.
- Add smoke-test scripts for each snippet where possible: shell syntax checks,
  Node graph execution, and Maven example execution. Use a small fixture
  repository and no network-dependent model calls.
- Treat generated SDK API references as build artifacts checked into `docs/`
  only if the repository's Pages strategy requires committed output; otherwise
  deploy them as a Pages artifact and keep the source generators in version
  control. Choose one policy and document it in `RELEASING.md`.
- Make the maintainer of a public SDK responsible for its package README,
  source API docs, runnable example, and contract-fixture compatibility in the
  same pull request.

## One-time external configuration

Before the first non-dry release:

- npm: create the scope/package, enable package provenance, and configure this
  repository/workflow/environment as a trusted publisher;
- Maven Central: verify the `io.github.tensilestream` namespace, create a
  Central Portal publishing token, register a signing key, and add protected
  `maven-central` environment secrets/variables;
- PyPI: retain the existing trusted-publishing configuration;
- GitHub: give the release workflow contents-write access only where it creates
  tags/releases/formula commits, and protect the `npm` and `maven-central`
  environments with required reviewers if desired;
- Homebrew: decide the repository formula versus a tap and ensure the release
  bot has permission for the selected destination.

No credential belongs in source, a checked-in Maven `settings.xml`, or an npm
configuration file.

## Delivery sequence

Implement and review in these separately testable commits:

1. contract fixtures and Python fixture tests;
2. Node adapter, package build, and consumer smoke test;
3. Java/LangGraph4j adapter, Maven metadata, and consumer smoke test;
4. version synchronization, formula/updater, and release preflight;
5. CI/release workflow and documentation; then configure registries and run a
   workflow-dispatch dry run;
6. publish a prerelease tag, install every artifact into blank consumers, and
   only then make the first stable release.

## Definition of done

A release is complete only when all checks below pass for the same `X.Y.Z`:

- Python, npm, Maven, GitHub Release assets, and formula have the same version;
- `npm pack`, Maven `verify`, formula audit, and clean-room installations pass;
- a LangGraph.js and a LangGraph4j sample graph produce the same fixture verdict
  objects, default route, attempt count, and loop behaviour as Python;
- `unverified` never routes to `pass` unless a caller explicitly overrides it;
- a non-zero CLI exit carrying valid verdict JSON remains a normal graph result;
- packages are published from validated artifacts with provenance/signatures as
  appropriate; and
- `RELEASING.md`, each SDK README, and graph examples give copyable install and
  wiring commands.
