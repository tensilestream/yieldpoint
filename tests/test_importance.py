"""Importance derived from the repository, rather than declared by a person.

A hand-written list of important paths is written once and then rots: a
directory is renamed and it silently stops matching, which is the worst failure
a safety control can have. Most of what it is trying to say — *how much breaks
if this is wrong* — is already in the import graph.

These tests pin the parts that make that trustworthy: the ranking is relative
to the repository, a missing graph makes the rules dormant rather than wrong,
and a stale cache is never preferred to a correct answer.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from yieldpoint.core.importcache import cached, fingerprint, forget, load_or_build
from yieldpoint.core.importgraph import build
from yieldpoint.harness import Change, risk, tier
from yieldpoint.scan import unmatched_patterns

PLAIN = "def f(a):\n    \"\"\"one\"\"\"\n    return a\n"
EDIT = "def f(a):\n    \"\"\"two\"\"\"\n    return a\n"


def _repo(root: Path, hub_importers: int) -> None:
    (root / "hub.py").write_text("VALUE = 1\n")
    (root / "lonely.py").write_text("OTHER = 2\n")
    for i in range(hub_importers):
        (root / f"user_{i}.py").write_text("from hub import VALUE\n\nx = VALUE\n")


class TestGraph(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        _repo(self.root, hub_importers=12)
        self.graph = build(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_it_counts_who_imports_what(self):
        self.assertEqual(self.graph.depends_on_me("hub.py"), 12)
        self.assertEqual(self.graph.depends_on_me("lonely.py"), 0)

    def test_external_imports_do_not_count(self):
        """Otherwise the ranking is led by `typing`, which says nothing."""
        (self.root / "user_0.py").write_text("import os\nimport json\nimport typing\n")
        graph = build(self.root)
        self.assertNotIn("os", graph.fan_in)
        self.assertNotIn("typing", graph.fan_in)

    def test_importance_is_a_percentile_not_a_count(self):
        """So one default works for a small service and a large monolith."""
        small = build(self.root)
        big = Path(tempfile.mkdtemp())
        _repo(big, hub_importers=200)
        for i in range(200):
            (big / f"filler_{i}.py").write_text("x = 1\n")
        large = build(big)
        self.assertGreater(small.importance("hub.py"), 0.9)
        self.assertGreater(large.importance("hub.py"), 0.9)

    def test_a_file_outside_the_graph_is_not_reported_as_unimportant(self):
        self.assertEqual(self.graph.importance("not/in/repo.py"), 0.0)
        self.assertEqual(self.graph.depends_on_me("not/in/repo.py"), 0)


class TestRiskUsesIt(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        _repo(self.root, hub_importers=30)
        self.graph = build(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_same_edit_differs_by_blast_radius(self):
        """The whole argument: no configuration, different answers."""
        hub = risk(Change("hub.py", PLAIN, EDIT), graph=self.graph)
        lonely = risk(Change("lonely.py", PLAIN, EDIT), graph=self.graph)
        self.assertEqual(hub.value, "high")
        self.assertEqual(lonely.value, "trivial")
        self.assertIn("import this one", hub.reason)

    def test_it_routes_the_load_bearing_edit_to_a_better_model(self):
        self.assertEqual(tier(Change("hub.py", PLAIN, EDIT), graph=self.graph).value,
                         "capable")
        self.assertEqual(tier(Change("lonely.py", PLAIN, EDIT), graph=self.graph).value,
                         "small")

    def test_without_a_graph_the_rule_is_dormant_not_wrong(self):
        """No graph must not read as "nothing depends on this"."""
        decision = risk(Change("hub.py", PLAIN, EDIT))
        self.assertEqual(decision.value, "trivial")
        self.assertIsNone(decision.signals["depended_on_by"])

    def test_the_threshold_is_configurable(self):
        relaxed = {"routing": {"critical_importance": 1.0}}
        self.assertEqual(
            risk(Change("hub.py", PLAIN, EDIT), relaxed, graph=self.graph).value,
            "trivial",
        )

    def test_it_can_be_switched_off_entirely(self):
        from yieldpoint.harness import middleware

        mw = middleware({"routing": {"use_import_graph": False}}, root=str(self.root))
        self.assertIsNone(mw._graph())


class TestCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        _repo(self.root, hub_importers=5)
        forget()

    def tearDown(self):
        forget()
        self.tmp.cleanup()

    def test_a_cached_graph_matches_a_fresh_one(self):
        first = load_or_build(self.root)
        second = load_or_build(self.root)
        self.assertEqual(first.fan_in, second.fan_in)

    def test_the_fingerprint_changes_when_the_tree_does(self):
        before = fingerprint(self.root)
        (self.root / "new_module.py").write_text("from hub import VALUE\n")
        self.assertNotEqual(before, fingerprint(self.root))

    def test_a_stale_cache_is_rebuilt_not_trusted(self):
        load_or_build(self.root)
        (self.root / "extra_user.py").write_text("from hub import VALUE\n")
        self.assertEqual(load_or_build(self.root).depends_on_me("hub.py"), 6)

    def test_a_corrupt_cache_is_rebuilt(self):
        load_or_build(self.root)
        (self.root / ".yieldpoint" / "importgraph.json").write_text("{not json")
        self.assertEqual(load_or_build(self.root).depends_on_me("hub.py"), 5)

    def test_the_cache_directory_ignores_itself(self):
        load_or_build(self.root)
        marker = self.root / ".yieldpoint" / ".gitignore"
        self.assertTrue(marker.is_file())

    def test_refresh_rereads_the_tree(self):
        cached(self.root)
        (self.root / "another.py").write_text("from hub import VALUE\n")
        self.assertEqual(cached(self.root, refresh=True).depends_on_me("hub.py"), 6)


class TestDeadConfiguration(unittest.TestCase):
    """A pattern that matches nothing must be reported, not assumed to work."""

    def test_it_names_the_pattern_protecting_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "a.py").write_text("x = 1\n")
            dead = unmatched_patterns(root, ["src/**", "billing/**", "nope/*.py"])
        self.assertEqual(sorted(dead), ["billing/**", "nope/*.py"])

    def test_no_patterns_means_nothing_to_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(unmatched_patterns(tmp, ()), ())


if __name__ == "__main__":
    unittest.main()
