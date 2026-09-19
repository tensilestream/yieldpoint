"""Fail the test run if the test suite itself was weakened.

Copy into ``conftest.py``. Cheap enough to leave on: it reads the uncommitted
diff once per session, makes no model calls, and adds no dependency.

Useful because it catches the weakening at the moment someone runs the tests —
before CI, and before a green run creates the impression of a green suite.
"""

from __future__ import annotations

import pytest

CONTRACT_RULES = {
    "assertion_monotonicity", "vacuous_assertion",
    "empty_test", "skip_marker", "disabled_assertion",
}


def pytest_sessionfinish(session, exitstatus):
    """A passing suite that was weakened to pass is the case worth catching."""
    if exitstatus != 0:
        return  # already failing; adding a second reason helps nobody

    try:
        from aegisflow.verify import verify_diff
        from aegisflow.worktree import uncommitted
    except ImportError:
        return

    diff = uncommitted(str(session.config.rootpath))
    if not diff.ok:
        return

    verdict = verify_diff(diff.text, diff.root)
    offences = [f for f in verdict.findings if f.rule in CONTRACT_RULES]
    if not offences:
        return

    session.exitstatus = 1
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter:
        reporter.write_sep("=", "AegisFlow: the suite passed because it was weakened",
                           red=True)
        for finding in offences:
            reporter.write_line(f"{finding.location}  {finding.detail}")
            reporter.write_line(f"    {finding.prescription}")


@pytest.fixture(scope="session")
def aegis_policy():
    """The active policy, for tests that want to assert on their own rules."""
    from aegisflow.core.policy import Policy

    return Policy.load(None)
