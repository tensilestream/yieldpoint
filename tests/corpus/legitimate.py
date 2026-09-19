"""Refactors a person performs on purpose. Every one must be silent.

A false positive here is the failure that gets the tool uninstalled: an
engineer who is told they weakened a test they in fact improved stops reading
the output, and a guardrail nobody reads is not a guardrail.
"""

from __future__ import annotations

from .case import HOLDOUT, TUNED, Case

LEGITIMATE = (
    Case("pytest to unittest port",
         "def test_a():\n    assert calc(2) == 4\n",
         "import unittest\nclass TestA(unittest.TestCase):\n"
         "    def test_a(self):\n        self.assertEqual(calc(2), 4)\n", TUNED),
    Case("exact float becomes approx",
         "def test_rate():\n    assert rate() == 0.1\n",
         "import pytest\ndef test_rate():\n    assert rate() == pytest.approx(0.1)\n", TUNED),
    Case("shared assertions extracted into a helper",
         "def test_a():\n    assert user.name == 'x'\n    assert user.age == 3\n",
         "def check_user(user):\n    assert user.name == 'x'\n    assert user.age == 3\n\n"
         "def test_a():\n    check_user(user)\n", TUNED),
    Case("sync test becomes async",
         "def test_fetch():\n    assert fetch() == 200\n",
         "import pytest\n@pytest.mark.asyncio\n"
         "async def test_fetch():\n    assert (await fetch()) == 200\n", TUNED),
    Case("setup extracted into a fixture parameter",
         "def test_total():\n    assert inv.total == 100\n",
         "def test_total(inv):\n    assert inv.total == 100\n", TUNED),
    Case("dict equality decomposed into field assertions",
         "def test_resp():\n    assert resp == {'a': 1, 'b': 2}\n",
         "def test_resp():\n    assert resp['a'] == 1\n    assert resp['b'] == 2\n", TUNED),
    Case("two tests merged by parametrisation",
         "def test_c():\n    assert f(1) == 1\n    assert f(2) == 4\n",
         "import pytest\n@pytest.mark.parametrize('n,e', [(1,1),(2,4)])\n"
         "def test_c(n, e):\n    assert f(n) == e\n", TUNED),
    Case("subject variable renamed",
         "def test_x():\n    result = compute()\n    assert result.total == 5\n",
         "def test_x():\n    outcome = compute()\n    assert outcome.total == 5\n", TUNED),
    Case("return type annotation added",
         "def test_x():\n    assert total == 5\n",
         "def test_x() -> None:\n    assert total == 5\n", TUNED),
    Case("grouped into a class",
         "def test_x():\n    assert total == 5\n",
         "class TestGroup:\n    def test_x(self):\n        assert total == 5\n", TUNED),
    Case("raises gains a match pattern",
         "import pytest\ndef test_x():\n    with pytest.raises(ValueError):\n        boom()\n",
         "import pytest\ndef test_x():\n"
         "    with pytest.raises(ValueError, match='bad'):\n        boom()\n", TUNED),
    Case("docstring added",
         "def test_x():\n    assert total == 5\n",
         'def test_x():\n    """Totals add up."""\n    assert total == 5\n', TUNED),

    Case("helper calling a helper, assertions added",
         "def field_ok(v):\n    assert v == 7\n\ndef row_ok(r):\n    field_ok(r.x)\n\n"
         "def test_r():\n    row_ok(load())\n",
         "def field_ok(v):\n    assert v == 7\n\ndef row_ok(r):\n    field_ok(r.x)\n\n"
         "def test_r():\n    row_ok(load())\n    assert load().y == 1\n", HOLDOUT),
    Case("reformatted across several lines",
         "def test_x():\n    assert compute(a, b) == 42\n",
         "def test_x():\n    assert (\n        compute(\n            a,\n            b,\n"
         "        )\n        == 42\n    )\n", HOLDOUT),
    Case("assertions reordered after tuple unpacking",
         "def test_x():\n    a, b = split()\n    assert a == 1\n    assert b == 2\n",
         "def test_x():\n    a, b = split()\n    assert b == 2\n    assert a == 1\n", HOLDOUT),
    Case("list equality decomposed by index",
         "def test_x():\n    assert items == [10, 20]\n",
         "def test_x():\n    assert items[0] == 10\n    assert items[1] == 20\n", HOLDOUT),
    Case("helper gains an optional keyword argument",
         "def ok(u):\n    assert u.name == 'a'\n\ndef test_u():\n    ok(load())\n",
         "def ok(u, strict=True):\n    assert u.name == 'a'\n\n"
         "def test_u():\n    ok(u=load())\n", HOLDOUT),
    Case("helper called with an awaited argument",
         "def ok(u):\n    assert u.id == 3\n\ndef test_u():\n    ok(fetch())\n",
         "import pytest\ndef ok(u):\n    assert u.id == 3\n\n"
         "@pytest.mark.asyncio\nasync def test_u():\n    ok(await fetch())\n", HOLDOUT),
    Case("property becomes a getter inside a helper",
         "def ok(o):\n    assert o.total == 9\n\ndef test_o():\n    ok(make())\n",
         "def ok(o):\n    assert o.getTotal() == 9\n\ndef test_o():\n    ok(make())\n", HOLDOUT),
)

__all__ = ["LEGITIMATE"]
