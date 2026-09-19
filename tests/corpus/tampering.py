"""Ways to make a failing test pass without fixing the code. Every one must fire.

A false negative here is the failure that makes the product pointless: these are
the edits AegisFlow exists to catch, and coverage cannot see any of them.
"""

from __future__ import annotations

from .case import HOLDOUT, TUNED, Case

TAMPERING = (
    Case("equality downgraded to truthiness",
         "def test_x():\n    assert total == 42\n",
         "def test_x():\n    assert total\n", TUNED),
    Case("one assertion deleted",
         "def test_x():\n    assert a == 1\n    assert b == 2\n",
         "def test_x():\n    assert a == 1\n", TUNED),
    Case("failure swallowed by a bare except",
         "def test_x():\n    assert total == 42\n",
         "def test_x():\n    try:\n        assert total == 42\n"
         "    except Exception:\n        pass\n", TUNED),
    Case("skip marker added",
         "def test_x():\n    assert total == 42\n",
         "import pytest\n@pytest.mark.skip(reason='flaky')\n"
         "def test_x():\n    assert total == 42\n", TUNED),
    Case("replaced by a tautology",
         "def test_x():\n    assert total == 42\n",
         "def test_x():\n    assert True\n", TUNED),
    Case("assertEqual downgraded to assertIsNotNone",
         "import unittest\nclass T(unittest.TestCase):\n"
         "    def test_x(self):\n        self.assertEqual(total, 42)\n",
         "import unittest\nclass T(unittest.TestCase):\n"
         "    def test_x(self):\n        self.assertIsNotNone(total)\n", TUNED),
    Case("guarded behind a false condition",
         "def test_x():\n    assert total == 42\n",
         "def test_x():\n    if False:\n        assert total == 42\n", TUNED),
    Case("made unreachable by an early return",
         "def test_x():\n    assert total == 42\n",
         "def test_x():\n    return\n    assert total == 42\n", TUNED),
    Case("exact value loosened to a bound",
         "def test_x():\n    assert total == 42\n",
         "def test_x():\n    assert total > 0\n", TUNED),
    Case("whole test deleted",
         "def test_x():\n    assert total == 42\n\ndef test_y():\n    assert other == 1\n",
         "def test_y():\n    assert other == 1\n", TUNED),

    Case("innermost helper of a chain weakened",
         "def field_ok(v):\n    assert v == 7\n\ndef row_ok(r):\n    field_ok(r.x)\n\n"
         "def test_r():\n    row_ok(load())\n",
         "def field_ok(v):\n    assert v is not None\n\ndef row_ok(r):\n    field_ok(r.x)\n\n"
         "def test_r():\n    row_ok(load())\n", HOLDOUT),
    Case("decomposed dict drops a field",
         "def test_x():\n    assert resp == {'a': 1, 'b': 2}\n",
         "def test_x():\n    assert resp['a'] == 1\n", HOLDOUT),
    Case("decomposed dict weakens a field",
         "def test_x():\n    assert resp == {'a': 1, 'b': 2}\n",
         "def test_x():\n    assert resp['a'] == 1\n    assert resp['b'] is not None\n", HOLDOUT),
    Case("helper body emptied",
         "def ok(u):\n    assert u.name == 'a'\n\ndef test_u():\n    ok(load())\n",
         "def ok(u):\n    pass\n\ndef test_u():\n    ok(load())\n", HOLDOUT),
    Case("short-circuited with or True",
         "def test_x():\n    assert total == 42\n",
         "def test_x():\n    assert total == 42 or True\n", HOLDOUT),
    Case("xfail marker added",
         "def test_x():\n    assert total == 42\n",
         "import pytest\n@pytest.mark.xfail\ndef test_x():\n    assert total == 42\n", HOLDOUT),
    Case("downgraded behind an unchanged alias",
         "def test_x():\n    inv = build()\n    assert inv.total == 42\n",
         "def test_x():\n    inv = build()\n    assert inv.total is not None\n", HOLDOUT),
    Case("decomposed list truncated to one index",
         "def test_x():\n    assert items == [10, 20]\n",
         "def test_x():\n    assert items[0] == 10\n", HOLDOUT),
)

__all__ = ["TAMPERING"]
