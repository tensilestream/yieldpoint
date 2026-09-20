# Contributing

## Running things

```sh
python -m unittest discover -s tests -t . -q    # no dependencies required
./scripts/release-check.sh                      # full pre-flight
yieldpoint scan yieldpoint --policy .yieldpoint.json   # Yieldpoint on itself
```

The core has no runtime dependencies and the tests use `unittest` from the standard
library, so a bare interpreter is enough. That is deliberate: it is what proves the
zero-dependency claim.

## The rules this codebase holds itself to

They are in [RULES.md](./RULES.md). Four are worth repeating because they are the ones
pull requests most often miss.

**Findings are differential.** A problem that existed before a change is not attributed to
it. Without this, switching a rule on in an existing repository produces a wall of findings
nobody caused, and the tool gets muted.

**Uncertainty must not block.** If analysis can be wrong — a third-party tool, a lexical
parse, a file whose generated half is missing — the finding is marked `LEXICAL`,
`UNRESOLVED` or `EXTERNAL`, and `Finding.__post_init__` refuses to let it block. Prefer a
false negative to a false positive, every time.

**Nothing is silently passed.** A file that could not be analysed goes in `skipped`, never
in `checked`. A surface that cannot evaluate says "not evaluated", never "PASSED".

**No claim without a benchmark.** No latency or percentage figure goes in any document,
comment or log line unless a reader can reproduce it.

## Adding a rule

1. Measurement goes in one module, judgement in another — thresholds and severities belong
   to policy, not to code.
2. Tests in both directions: what it must catch, **and** the legitimate code it must not
   flag. The second half is the one that decides whether the rule survives contact with a
   real repository.
3. Default to `repair`. A new rule that defaults to `block` will fail somebody's pipeline
   on an upgrade.
4. Add it to the table in `README.md` and to `CHANGELOG.md`.

## Commits and releases

Commits and tags are made by maintainers; see [RELEASING.md](./RELEASING.md). Tags are
`vMAJOR.MINOR.PATCH` and annotated.

## Licensing of contributions

Yieldpoint is licensed under the [Business Source License 1.1](./LICENSE) and sold
commercially above the free tier, so code contributions need a sign-off that lets the
project license your work on the same terms. Add this to a commit in your pull request:

```
Signed-off-by: Your Name <your@email>
```

You keep your copyright. [CLA.md](./CLA.md) says exactly what that grants and why it is
necessary — it is one page, and worth reading before you spend time on a patch.

**Bug reports, false positives and missed detections need no sign-off**, and are the most
useful thing you can send.
