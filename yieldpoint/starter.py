"""The policy `yieldpoint init` writes into a new repository.

Separated from install.py because the two change for different reasons:
this file when a default should differ, that one when a wiring step does.

Deliberately small. A starter config that turns everything on gets edited
down in anger; one that starts advisory gets tuned up on purpose.
"""

from __future__ import annotations

STARTER_CONFIG = {
    "version": 1,
    "test_contract": {
        "_comment": "Severities: repair (send the agent back), escalate (ask a "
                    "human), block (refuse), or null to switch a rule off.",
        "assertion_monotonicity": "repair",
        "forbid_vacuous_assertions": "repair",
        "forbid_new_skip_markers": "repair",
        "forbid_swallowed_exceptions": "repair",
    },
    "structure": {
        "_comment": "Differential by default: a limit is reported only when this "
                    "change introduced or worsened the violation, so existing debt "
                    "is not blamed on the current edit.",
        "greenfield": False,
        "severity": "repair",
        "_exclude_comment": "Paths these limits skip, as globs — a directory, an "
                            "exact file, or an extension. Only maintainability is "
                            "skipped: an excluded file is still checked for a "
                            "weakened test contract.",
        "exclude": [
            "**/*_pb2.py",
            "**/migrations/**",
            "**/vendor/**",
            "**/*.generated.py",
        ],
    },
}

__all__ = ["STARTER_CONFIG"]
