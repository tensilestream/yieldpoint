"""The analysis cache.

A cache that feeds a safety decision has exactly one unbreakable property: a
hit must be indistinguishable from a recomputation. Everything else here —
speed, bounds, surviving concurrent writers — matters only because the first
property holds.

It is keyed by a hash of the source rather than by path, which is what makes a
renamed file, or the same file at a different commit, a hit.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from aegisflow.core import metrics, parsecache, symbols

ROOT = Path(__file__).resolve().parent.parent

SOURCES = [
    "x = 1\n",
    "import os\n\ndef f(a, b):\n    if a:\n        return b\n    return a\n",
    "class A:\n    def m(self):\n        for i in range(3):\n            yield i\n",
    "def broken(:\n",
]

WRITER = """
import sys
sys.path.insert(0, ROOT_PATH)
from aegisflow.core import metrics, parsecache
parsecache.configure(sys.argv[1])
for i in range(40):
    metrics.measure("def f_" + str(i) + "():\\n    return " + str(i) + "\\n",
                    filename="w.py")
"""


class TestAHitEqualsARecomputation(unittest.TestCase):
    """The property everything else rests on."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        parsecache.configure(self.tmp.name)
        parsecache.clear()

    def tearDown(self):
        parsecache.close()
        parsecache.configure(".")
        parsecache.clear()
        self.tmp.cleanup()

    def test_metrics_match_the_uncached_routine(self):
        for source in SOURCES:
            with self.subTest(source[:20]):
                parsecache.clear()
                first = metrics.measure(source, filename="a.py")
                parsecache.clear()          # force a database read
                second = metrics.measure(source, filename="a.py")
                self.assertEqual(first, second)
                self.assertEqual(first, metrics._measure(source, "a.py"))

    def test_symbols_match_the_uncached_routine(self):
        for source in SOURCES:
            with self.subTest(source[:20]):
                parsecache.clear()
                first = symbols.scan(source, filename="a.py")
                parsecache.clear()
                second = symbols.scan(source, filename="a.py")
                self.assertEqual(first, second)
                self.assertEqual(first, symbols._scan(source, "a.py"))

    def test_an_unparseable_file_caches_its_error_too(self):
        broken = "def f(:\n"
        parsecache.clear()
        self.assertFalse(metrics.measure(broken, filename="a.py").ok)
        parsecache.clear()
        self.assertFalse(metrics.measure(broken, filename="a.py").ok)


class TestKeying(unittest.TestCase):
    def test_the_filename_is_not_part_of_the_key(self):
        """A renamed file, or the same file at another commit, is the same input."""
        source = "def f():\n    return 1\n"
        self.assertEqual(
            parsecache.key(source, "metrics"), parsecache.key(source, "metrics")
        )

    def test_different_sources_do_not_collide(self):
        self.assertNotEqual(
            parsecache.key("a = 1\n", "metrics"), parsecache.key("a = 2\n", "metrics")
        )

    def test_different_analysers_do_not_collide(self):
        source = "a = 1\n"
        self.assertNotEqual(
            parsecache.key(source, "metrics"), parsecache.key(source, "symbols")
        )


class TestItFailsSafe(unittest.TestCase):
    """The cache may make things slow. It may not make them wrong."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        parsecache.configure(self.root)
        parsecache.clear()

    def tearDown(self):
        parsecache.close()
        parsecache.configure(".")
        parsecache.clear()
        self.tmp.cleanup()

    def test_a_corrupt_database_still_returns_the_right_answer(self):
        source = "def f():\n    return 1\n"
        expected = metrics._measure(source, "a.py")
        database = self.root / parsecache.DEFAULT_PATH
        database.parent.mkdir(parents=True, exist_ok=True)
        database.write_bytes(b"this is not a database")
        parsecache.clear()
        self.assertEqual(metrics.measure(source, filename="a.py"), expected)

    def test_an_unwritable_location_still_returns_the_right_answer(self):
        parsecache.close()
        parsecache.configure("/proc/nowhere")
        parsecache.clear()
        source = "def f():\n    return 2\n"
        self.assertEqual(
            metrics.measure(source, filename="a.py"), metrics._measure(source, "a.py")
        )

    def test_the_cache_directory_ignores_itself(self):
        metrics.measure("a = 1\n", filename="a.py")
        marker = (self.root / parsecache.DEFAULT_PATH).parent / ".gitignore"
        self.assertTrue(marker.is_file())


class TestConcurrentWriters(unittest.TestCase):
    def test_many_processes_can_write_at_once(self):
        """Several agents verifying against one repository is the normal case."""
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "writer.py"
            script.write_text(WRITER.replace("ROOT_PATH", repr(str(ROOT))))
            procs = [
                subprocess.Popen([sys.executable, str(script), tmp],
                                 stderr=subprocess.PIPE)
                for _ in range(6)
            ]
            results = []
            for proc in procs:
                code = proc.wait(timeout=120)
                error = proc.stderr.read().decode()
                proc.stderr.close()
                results.append((code, error))
        for code, error in results:
            self.assertEqual(code, 0, f"a writer failed under contention: {error[-300:]}")


if __name__ == "__main__":
    unittest.main()
