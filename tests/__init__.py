"""Test package.

Recording is off during this suite, but not because anything here switches it
off: ``ledger.under_test()`` detects a test run and declines to record, which
is the same protection every project gets. Setting an environment variable here
as well would hide whether that detection works.

Tests that need recording write to a temporary path with ``ledger.record``
directly, which is the layer below the switch. Tests that need a surface to
record set ``AEGISFLOW_METRICS=1``.
"""
