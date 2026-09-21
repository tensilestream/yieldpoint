"""The policy `yieldpoint init` writes into a repository.

Separated from install.py because the two change for different reasons:
this file when a default should differ, that one when a wiring step does.

**Every limit in force is written out, including the ones whose value is
"off".** A field review found a repository being blocked by a 300-line limit
that appeared in no file the reviewer could open — it was a default compiled
into the tool. A config that omits a setting because the default is fine is a
config that hides what is being enforced, and the person it hides it from is
the person being stopped.

Writing the numbers has a consequence taken on purpose: a repository whose
policy names its thresholds does not inherit new defaults when Yieldpoint is
upgraded. For most tools that is a drawback. For this one it is the point — a
verdict on an unchanged commit that changes because the checker was upgraded is
the exact failure this checker exists to report.

Deliberately quiet. A starter config that turns everything on gets edited down
in anger; one that starts advisory gets tuned up on purpose.
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
        "_limits_comment": "Every limit in force, listed so none of them is "
                           "invisible. null switches one off.",
        "max_file_lines": None,
        "max_lines": 50,
        "max_parameters": 5,
        "max_nesting": 4,
        "max_complexity": 10,
        "max_added_lines": 400,
        "max_change_lines": 1200,
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
    "metrics": {
        "_comment": "Local accounting, on by default: a value claim nobody can "
                    "check is worth nothing. Nothing leaves the machine — this "
                    "package makes no network call. Listed here because it writes "
                    "a file into your repository, and a tool that creates a "
                    "directory you did not ask for should say so in a file you "
                    "can read. Set enabled false, or export YIELDPOINT_NO_METRICS.",
        "enabled": True,
        "path": ".yieldpoint/metrics.jsonl",
    },
}

__all__ = ["STARTER_CONFIG"]
