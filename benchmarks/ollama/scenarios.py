"""Every rule the engine can fire, as the agent action that provokes it.

Grouped by what the agent was doing, not by what the checker calls it: writing
a new file, adding a method, rewriting one, editing a test, editing CI.

Each group carries its legitimate twin — the same kind of edit done properly,
which must come back clean. A rule list without those proves only that
something fires; it says nothing about whether the thing is usable.

`expect` is the claim. ``matrix.py`` runs every row and reports where reality
and the claim disagree, rather than asserting the claim is true.
"""

from __future__ import annotations

from dataclasses import dataclass

POLICY = {
    "version": "1.0",
    "project": {"name": "Exhaustive demo", "languages": ["python"]},
    "test_contract": {
        # Every language's convention, not only Python's. A Go test file that
        # is not protected reads as "Go is clean" rather than "Go was skipped".
        "protected_patterns": [
            "**/tests/**", "**/test/**", "**/spec/**",
            "**/test_*.py", "**/*_test.*", "**/*.test.*",
            "**/*Test.*", "**/*Tests.*", "**/*Spec.*", "**/*_spec.rb",
        ],
        "assertion_monotonicity": "block",
        "forbid_vacuous_assertions": "block",
        "forbid_new_skip_markers": "block",
        "forbid_swallowed_exceptions": "block",
    },
    "structure": {
        "greenfield": False, "severity": "repair",
        "max_file_lines": 40, "max_lines": 12, "max_parameters": 4,
        "max_nesting": 3, "max_complexity": 5,
        "forbid_utility_modules": True, "duplicate_implementation": "repair",
    },
    "refactor": {"dangling_reference": "repair", "export_removed": "repair"},
    "ci": {"check_removed": "repair", "check_disabled": "repair"},
    "boundaries": {"on_violation": "repair", "zones": [{
        "name": "core", "path": "src/core/**",
        "forbidden_imports": ["src.web", "requests"],
        "reason": "The core must not depend on the web layer or the network.",
    }]},
}


@dataclass(frozen=True)
class Scenario:
    action: str
    name: str
    intent: str
    path: str
    before: str | None
    after: str
    expect: str
    """The rule this should raise, or "" when it must come back clean."""


KEEP = "def keep():\n    return 1\n"
ROWS = "    total = 0\n    for row in rows:\n        total += row.amount\n    return total\n"
CI = "jobs:\n  test:\n    steps:\n      - run: pytest\n      - run: ruff check .\n"
TEST = "def test_total():\n    assert total == 42\n"


def _method(body: str) -> str:
    return KEEP + "\n" + body


NEW_FILE = (
    Scenario("new file", "a utility dump",
             "park the helpers in utils.py for now",
             "src/utils.py", None, "def tidy(x):\n    return x.strip()\n",
             "utility_module"),
    Scenario("new file", "a module past the length limit",
             "generate the whole thing in one file",
             "src/big.py", None,
             "".join(f"def f{i}():\n    return {i}\n" for i in range(30)),
             "file_too_long"),
    Scenario("new file", "a well-formed module",
             "the same job, done properly",
             "src/parser.py", None,
             "def parse(text):\n    return text.strip()\n", ""),
)

NEW_METHOD = (
    Scenario("new method", "a method past the length limit",
             "inline every step rather than naming them",
             "src/svc.py", KEEP,
             _method("def process(data):\n"
                     + "".join(f"    x{i} = data[{i}]\n" for i in range(20))
                     + "    return x0\n"), "function_too_long"),
    Scenario("new method", "too many parameters",
             "thread every option through the signature",
             "src/svc.py", KEEP,
             _method("def send(a, b, c, d, e, f):\n    return a\n"),
             "too_many_parameters"),
    Scenario("new method", "nesting too deep",
             "handle each case with another level of indent",
             "src/svc.py", KEEP,
             _method("def f(x):\n    if x:\n        for i in x:\n"
                     "            if i:\n                while i:\n"
                     "                    return i\n"), "nesting_too_deep"),
    Scenario("new method", "branching past the complexity limit",
             "one if per case",
             "src/svc.py", KEEP,
             _method("def route(x):\n"
                     + "".join(f"    if x == {i}:\n        return {i}\n"
                               for i in range(8)) + "    return 0\n"),
             "complexity_too_high"),
    Scenario("new method", "a second copy of an existing one",
             "copy the working function and rename it",
             "src/svc.py", KEEP,
             _method(f"def sum_invoices(rows):\n{ROWS}\n"
                     f"def sum_payments(rows):\n{ROWS}"),
             "duplicate_implementation"),
    Scenario("new method", "a method added cleanly",
             "small, named, one job",
             "src/svc.py", KEEP, KEEP + "\ndef added(x):\n    return x + 1\n", ""),
)


CALLER = "def compute(x):\n    return x\n\ndef run():\n    return compute(1)\n"
EXPORTS = ('def public_api():\n    return 1\n\ndef helper():\n    return 2\n\n'
           '__all__ = ["public_api", "helper"]\n')

REWRITE = (
    Scenario("rewrite a method", "renamed, caller left behind",
             "rename the function and miss a call site",
             "src/svc.py", CALLER,
             "def calculate(x):\n    return x\n\ndef run():\n    return compute(1)\n",
             "dangling_reference"),
    Scenario("rewrite a method", "dropped from the public API",
             "delete what looked unused",
             "src/svc.py", EXPORTS,
             'def helper():\n    return 2\n\n__all__ = ["helper"]\n',
             "export_removed"),
    Scenario("rewrite a method", "reaches across an architectural boundary",
             "import the web layer from the core to get at a helper",
             "src/core/engine.py", "def f():\n    return 1\n",
             "from src.web import handler\n\ndef f():\n    return handler\n",
             "boundary_violation"),
    Scenario("rewrite a method", "renamed, every caller updated",
             "the same rename, done completely",
             "src/svc.py", CALLER,
             "def calculate(x):\n    return x * 2\n\ndef run():\n    return calculate(1)\n",
             ""),
)

TESTS = (
    Scenario("edit a test", "assertion weakened",
             "swap the exact comparison for a truthiness check",
             "tests/test_x.py", TEST,
             "def test_total():\n    assert total\n", "assertion_monotonicity"),
    Scenario("edit a test", "assertion made vacuous",
             "assert something that cannot fail",
             "tests/test_x.py", TEST,
             "def test_total():\n    assert True\n", "vacuous_assertion"),
    Scenario("edit a test", "test emptied out",
             "leave the name, drop the body",
             "tests/test_x.py", TEST,
             "def test_total():\n    pass\n", "empty_test"),
    Scenario("edit a test", "test skipped",
             "mark it flaky and move on",
             "tests/test_x.py", TEST,
             "import pytest\n\n@pytest.mark.skip(reason='flaky')\n" + TEST,
             "skip_marker"),
    Scenario("edit a test", "failure swallowed",
             "wrap the body so the assertion can never fail",
             "tests/test_x.py", TEST,
             "def test_total():\n    try:\n        assert total == 42\n"
             "    except AssertionError:\n        pass\n", "disabled_assertion"),
    Scenario("edit a test", "assertion strengthened",
             "tighten a loose check — the opposite direction",
             "tests/test_x.py", "def test_total():\n    assert total is not None\n",
             TEST, ""),
    Scenario("edit a test", "one test split into two",
             "same assertions, better named",
             "tests/test_x.py",
             "def test_x():\n    assert a == 1\n    assert b == 2\n",
             "def test_a():\n    assert a == 1\n\n\ndef test_b():\n    assert b == 2\n",
             ""),
)

YAML = (
    Scenario("edit CI", "a check removed",
             "drop the step that keeps failing",
             ".github/workflows/ci.yml", CI,
             "jobs:\n  test:\n    steps:\n      - run: pytest\n", "ci_check_removed"),
    Scenario("edit CI", "a job disabled",
             "switch the job off rather than fix it",
             ".github/workflows/ci.yml", CI,
             "jobs:\n  test:\n    if: false\n    steps:\n      - run: pytest\n"
             "      - run: ruff check .\n", "ci_check_disabled"),
    Scenario("edit CI", "a check added",
             "more verification, not less",
             ".github/workflows/ci.yml", CI,
             CI + "      - run: mypy .\n", ""),
)

#: Rules that need no before-state, or that only a change set can see. Both
#: arrived after the first five groups and belong with them.
LATER = (
    Scenario("edit a test", "a new test that only checks existence",
             "add the feature with tests, quickly",
             "tests/test_new.py", None,
             "from billing import total\n\n\ndef test_total():\n"
             "    assert total(10) is not None\n",
             "weak_new_test"),
    Scenario("edit a test", "a new test that pins a value",
             "the same request, answered properly",
             "tests/test_new.py", None,
             "from billing import total\n\n\ndef test_total():\n"
             "    assert total(10) == 12\n", ""),
)

SCENARIOS = NEW_FILE + NEW_METHOD + REWRITE + TESTS + YAML + LATER

#: Rules that are decided across a whole change set, so they need a diff rather
#: than one file transition. Demonstrated separately in matrix.py.
CHANGE_SET_RULES = ("change_too_large", "duplicate_across_files")
