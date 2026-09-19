"""The documentation site, checked against the engine.

Docs that drift are worse than none, because people act on them. The rules
reference is the part most likely to go stale — a rule gets added and nobody
remembers the page exists — so the coverage check runs here rather than relying
on whoever writes the next rule to think of it.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
BUILDER = ROOT / "scripts" / "build_docs.py"


class TestRulesReferenceIsComplete(unittest.TestCase):
    def test_every_rule_the_engine_emits_is_documented(self):
        result = subprocess.run(
            [sys.executable, str(BUILDER), "--check"],
            capture_output=True, text=True, cwd=str(ROOT))
        self.assertEqual(result.returncode, 0,
                         f"scripts/build_docs.py --check failed:\n{result.stderr}")

    def test_the_checker_would_notice_a_new_rule(self):
        """A check that cannot fail is not a check."""
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            import build_docs
        finally:
            sys.path.pop(0)
        engine = dict(build_docs.emitted_rules())
        engine["a_rule_nobody_documented"] = "yieldpoint/core/invented.py"
        original = build_docs.emitted_rules
        build_docs.emitted_rules = lambda: engine
        try:
            problems = build_docs.check_rules()
        finally:
            build_docs.emitted_rules = original
        self.assertTrue(any("a_rule_nobody_documented" in p for p in problems), problems)


class TestTheSiteIsBuilt(unittest.TestCase):
    """The committed pages must match what the generator produces."""

    def test_the_committed_pages_are_current(self):
        pages = sorted(p.name for p in DOCS.glob("*.html"))
        self.assertTrue(pages, "docs/ has no pages; run scripts/build_docs.py")
        before = {p: p.read_bytes() for p in DOCS.glob("*.html")}
        subprocess.run([sys.executable, str(BUILDER)],
                       capture_output=True, text=True, cwd=str(ROOT), check=True)
        stale = [p.name for p, content in before.items() if p.read_bytes() != content]
        self.assertEqual(stale, [],
                         "docs/ is out of date; run python3 scripts/build_docs.py")

    def test_every_page_links_only_to_pages_that_exist(self):
        import re

        names = {p.name for p in DOCS.glob("*.html")}
        broken = []
        for page in sorted(DOCS.glob("*.html")):
            for href in re.findall(r'href="([^"#:]+\.html)"', page.read_text()):
                if href not in names:
                    broken.append(f"{page.name} -> {href}")
        self.assertEqual(broken, [])

    def test_pages_are_well_formed(self):
        from html.parser import HTMLParser

        class Strict(HTMLParser):
            def __init__(self):
                super().__init__(convert_charrefs=True)
                self.stack = []
                self.void = {"meta", "link", "br", "hr", "img", "input"}

            def handle_starttag(self, tag, attrs):
                if tag not in self.void:
                    self.stack.append(tag)

            def handle_endtag(self, tag):
                if self.stack and self.stack[-1] == tag:
                    self.stack.pop()
                elif tag in self.stack:
                    raise AssertionError(f"</{tag}> closes out of order: {self.stack}")

        for page in sorted(DOCS.glob("*.html")):
            parser = Strict()
            parser.feed(page.read_text(encoding="utf-8"))
            self.assertEqual(parser.stack, [], f"{page.name} has unclosed tags")


if __name__ == "__main__":
    unittest.main()


class TestDocumentedCommandsExist(unittest.TestCase):
    """A quick start that names a command the CLI does not have is worse than none.

    The first draft of this page told people to run `yieldpoint install-git-gate`,
    which has never existed — the commit gate is installed by `init`. Nothing
    caught it, because prose is not executed. This executes it.
    """

    def _subcommands(self) -> set:
        import re
        out = subprocess.run([sys.executable, "-m", "yieldpoint.cli", "--help"],
                             capture_output=True, text=True, cwd=str(ROOT)).stdout
        listed = re.search(r"\{([a-z,\-]+)\}", out)
        self.assertIsNotNone(listed, out)
        return set(listed.group(1).split(","))

    def test_every_command_named_in_the_docs_exists(self):
        import re

        known = self._subcommands()
        pages = list(DOCS.glob("*.html")) + [ROOT / "README.md"]
        invented = set()
        for page in pages:
            for cmd in re.findall(r"\b(?:yp|yieldpoint) ([a-z][a-z-]{2,})\b",
                                  page.read_text(encoding="utf-8")):
                if cmd not in known:
                    invented.add(f"{page.name}: {cmd}")
        self.assertEqual(sorted(invented), [])

    def test_the_check_would_notice_an_invented_command(self):
        self.assertNotIn("install-git-gate", self._subcommands())
