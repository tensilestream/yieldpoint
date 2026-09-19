"""A committed corpus for measuring what the monotonicity check gets wrong.

RULES.md section 5 forbids stating a rate that a reader cannot reproduce, and
a measured false-positive rate is the gate a rule must pass before it is ever
allowed to block. This package is that
measurement, kept runnable::

    python -m tests.corpus

``LEGITIMATE`` holds refactors a person performs on purpose; every one of them
must be silent. ``TAMPERING`` holds ways an agent can make a failing test pass
without fixing the code; every one must be reported. A case in the wrong column
is a bug, not a tuning parameter.

The corpus is deliberately split by provenance. The ``tuned`` cases were used
while fixing the checker, so a perfect score on them proves only that the fixes
landed. The ``holdout`` cases were written afterwards and never consulted during
the fix; those are the ones that say anything about generalisation. Adding a new
case to ``tuned`` after using it to debug is honest; moving it to ``holdout`` is
not.
"""

from .case import HOLDOUT, TUNED, Case
from .legitimate import LEGITIMATE
from .tampering import TAMPERING

__all__ = ["LEGITIMATE", "TAMPERING", "Case", "TUNED", "HOLDOUT"]
