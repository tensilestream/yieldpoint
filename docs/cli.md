# CLI JSON contract

All non-Python bindings invoke this CLI; it is the one implementation of
Yieldpoint rules.

```sh
git diff origin/main...HEAD | yieldpoint check --diff - --root . --json
```

`--json` prints a schema-versioned verdict object. Consumers must require the
supported `schema_version`, preserve `findings`, `checked`, `skipped`, and
`acknowledged`, and route on `status`:

| Status | Meaning |
| --- | --- |
| `pass` | At least one rule checked the change and found no finding. |
| `unverified` | No rule evaluated the change; choose an explicit graph/CI route. |
| `repair` | Give the deterministic prescription back to the agent. |
| `escalate` | Require human review. |
| `block` | Do not apply the change. |

A successful JSON parse is authoritative even when the process exits `1`: that
exit means a normal finding. Treat missing executable, timeout, malformed JSON,
and unsupported schema versions as integration failures, never as `pass`.

For local developer gates use `yieldpoint init --no-hook` for the Git commit
gate, `yieldpoint install-hook --advisory` for reporting editor integration,
and `yieldpoint install-hook` to enforce supported editor writes. Pair hooks
with CI because direct filesystem writes and bypassed commits can evade a local
hook.
