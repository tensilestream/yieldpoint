"""Architectural boundaries.

This section of the policy file existed, and was declared by this repository's
own configuration, while nothing evaluated it — a rule that looks enforced and is
not. That is the failure this project was built to prevent, so these tests exist
as much to keep the rule wired up as to check its logic.
"""

import unittest
from pathlib import Path

from yieldpoint.core import boundaries
from yieldpoint.core.boundaries import BOUNDARY_VIOLATION, imports_of
from yieldpoint.core.policy import Boundaries, Policy, Zone
from yieldpoint.core.verdict import Status
from yieldpoint.verify import verify_change

CORE_ZONE = Boundaries(zones=(
    Zone(name="core", path="app/core/**",
         forbidden_imports=("app.adapters.*", "requests", "src/db/**"),
         reason="The core stays independent."),
))


def rules(before, after, path="app/core/thing.py", config=CORE_ZONE):
    return [f.rule for f in boundaries.check(before, after, path, config)[0]]


class TestImportResolution(unittest.TestCase):
    """A relative import that resolves to nothing silently disables a rule."""

    def test_absolute_imports(self):
        found = imports_of("import os\nfrom sys import argv\n", "app/core/x.py")
        self.assertEqual({i.module for i in found}, {"os", "sys"})

    def test_single_level_relative(self):
        found = imports_of("from . import glob\n", "yieldpoint/core/x.py")
        self.assertEqual(found[0].module, "yieldpoint.core")

    def test_two_level_relative(self):
        found = imports_of("from ..langgraph import node\n", "yieldpoint/core/x.py")
        self.assertEqual(found[0].module, "yieldpoint.langgraph")

    def test_relative_with_submodule(self):
        found = imports_of("from .verdict import Finding\n", "yieldpoint/core/x.py")
        self.assertEqual(found[0].module, "yieldpoint.core.verdict")

    def test_package_init_resolves_to_the_package_it_defines(self):
        """Inside `a/b/__init__.py`, `.` is `a.b` — not its parent."""
        found = imports_of("from . import x\n", "yieldpoint/core/__init__.py")
        self.assertEqual(found[0].module, "yieldpoint.core")

    def test_line_numbers_are_reported(self):
        found = imports_of("x = 1\nimport os\n", "app/core/x.py")
        self.assertEqual(found[0].line, 2)

    def test_unparseable_source_yields_nothing(self):
        self.assertEqual(imports_of("import (", "app/core/x.py"), ())


class TestPatterns(unittest.TestCase):
    def test_bare_package_forbids_everything_beneath_it(self):
        self.assertEqual(rules(None, "import requests\n"), [BOUNDARY_VIOLATION])
        self.assertEqual(rules(None, "import requests.adapters\n"), [BOUNDARY_VIOLATION])

    def test_a_similar_name_is_not_a_match(self):
        self.assertEqual(rules(None, "import requests_mock\n"), [])

    def test_wildcard_matches_submodules(self):
        self.assertEqual(rules(None, "from app.adapters.web import x\n"), [BOUNDARY_VIOLATION])

    def test_wildcard_also_matches_the_package_itself(self):
        """`a.b.*` means anything in a.b; importing a.b is importing from it."""
        self.assertEqual(rules(None, "from app import adapters\nimport app.adapters\n"),
                         [BOUNDARY_VIOLATION])

    def test_path_glob_form_is_supported(self):
        self.assertEqual(rules(None, "from src.db.models import User\n"), [BOUNDARY_VIOLATION])

    def test_an_allowed_import_is_silent(self):
        self.assertEqual(rules(None, "from app.core.other import x\nimport os\n"), [])


class TestScope(unittest.TestCase):
    def test_files_outside_any_zone_are_untouched(self):
        self.assertEqual(rules(None, "import requests\n", path="app/web/view.py"), [])

    def test_no_zones_means_no_findings(self):
        self.assertEqual(rules(None, "import requests\n", config=Boundaries()), [])

    def test_the_rule_can_be_disabled(self):
        config = Boundaries(on_violation=None, zones=CORE_ZONE.zones)
        self.assertEqual(rules(None, "import requests\n", config=config), [])

    def test_severity_comes_from_policy(self):
        config = Boundaries(on_violation=Status.ESCALATE, zones=CORE_ZONE.zones)
        findings, _ = boundaries.check(None, "import requests\n", "app/core/x.py", config)
        self.assertIs(findings[0].status, Status.ESCALATE)

    def test_the_zone_reason_becomes_the_prescription(self):
        findings, _ = boundaries.check(None, "import requests\n", "app/core/x.py", CORE_ZONE)
        self.assertEqual(findings[0].prescription, "The core stays independent.")


class TestDifferential(unittest.TestCase):
    def test_a_preexisting_violation_is_not_this_change_s_fault(self):
        source = "import requests\n\ndef f():\n    return 1\n"
        self.assertEqual(rules(source, source + "\ndef g():\n    return 2\n"), [])

    def test_a_newly_introduced_violation_is_reported(self):
        self.assertEqual(rules("def f():\n    return 1\n", "import requests\n"),
                         [BOUNDARY_VIOLATION])

    def test_removing_a_violation_is_silent(self):
        self.assertEqual(rules("import requests\n", "def f():\n    return 1\n"), [])


class TestThisRepository(unittest.TestCase):
    """The zones in this repo's own .yieldpoint.json must actually be enforced."""

    def setUp(self):
        self.policy = Policy.load(Path(__file__).resolve().parent.parent / ".yieldpoint.json")

    def violations(self, source, path):
        verdict = verify_change(None, source, path, self.policy)
        return [f for f in verdict.findings if f.rule == BOUNDARY_VIOLATION]

    def test_the_core_may_not_import_an_adapter(self):
        self.assertTrue(self.violations(
            "from yieldpoint.langgraph.node import verify_node\n", "yieldpoint/core/x.py"))

    def test_the_core_may_not_reach_the_network(self):
        self.assertTrue(self.violations("import httpx\n", "yieldpoint/core/x.py"))

    def test_the_core_may_not_import_langgraph(self):
        self.assertTrue(self.violations("import langgraph\n", "yieldpoint/core/x.py"))

    def test_an_adapter_may_not_use_core_internals(self):
        self.assertTrue(self.violations(
            "from yieldpoint.core.diff import parse\n", "yieldpoint/langgraph/x.py"))

    def test_an_adapter_may_use_the_verdict_api(self):
        self.assertEqual(self.violations(
            "from yieldpoint.core.verdict import Verdict\n", "yieldpoint/langgraph/x.py"), [])

    def test_the_core_may_import_itself(self):
        self.assertEqual(self.violations(
            "from .verdict import Finding\n", "yieldpoint/core/x.py"), [])

    def test_the_real_source_tree_has_no_violations(self):
        config = self.policy.boundaries
        root = Path(__file__).resolve().parent.parent
        for path in sorted((root / "yieldpoint").rglob("*.py")):
            relative = str(path.relative_to(root))
            findings, _ = boundaries.check(None, path.read_text(encoding="utf-8"), relative, config)
            self.assertEqual(findings, [], f"{relative}: {[f.detail for f in findings]}")


if __name__ == "__main__":
    unittest.main()
