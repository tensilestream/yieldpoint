"""``python -m tests.corpus`` — print the measured false-positive rate."""

import sys

from .measure import report

sys.exit(report())
