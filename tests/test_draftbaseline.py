"""Which baseline the per-edit gate judges a weakening against.

The gate compares an edit to the file on disk, which is what the *previous*
edit left. That answers "did this edit weaken the suite" and not "was there
anything here to weaken" — and an assertion written and reshaped minutes later,
inside one uncommitted session, is a draft being worked out.

The exemption is deliberately narrow, and the second class here is the reason:
new tests are exactly where tampering happens.
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from yieldpoint.hook import blocks, evaluate
from yieldpoint.worktree import at_head

COMMITTED = (
    "def test_total():\n    assert inv.total == 42\n\n\n"
    "def test_tax():\n    assert inv.tax == 7\n"
)
DRAFTED = COMMITTED + "\n\ndef test_net():\n    assert inv.net == 35\n"
DRAFT_WEAKENED = COMMITTED + "\n\ndef test_net():\n    assert inv.net is not None\n"
COMMITTED_WEAKENED = (
    "def test_total():\n    assert inv.total is not None\n\n\n"
    "def test_tax():\n    assert inv.tax == 7\n"
)


def _repository(directory: str, name: str, content: str) -> Path:
    """A real repository with one committed test file."""
    root = Path(directory)
    for command in (["init", "-q"], ["config", "user.email", "t@t"],
                    ["config", "user.name", "t"]):
        subprocess.run(["git", *command], cwd=root, check=True,
                       capture_output=True)
    path = root / name
    path.write_text(content)
    subprocess.run(["git", "add", name], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "first"], cwd=root, check=True,
                   capture_output=True)
    return path


def _verdict(path: Path, after: str):
    return evaluate({"tool_name": "Write",
                     "tool_input": {"file_path": str(path), "content": after}})[0]


class TestAtHead(unittest.TestCase):
    def test_it_reads_the_committed_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _repository(directory, "test_invoice.py", COMMITTED)
            path.write_text(DRAFTED)
            self.assertEqual(at_head(path, directory), COMMITTED)

    def test_an_untracked_file_has_no_committed_content(self):
        with tempfile.TemporaryDirectory() as directory:
            _repository(directory, "test_invoice.py", COMMITTED)
            other = Path(directory) / "test_new.py"
            other.write_text(DRAFTED)
            self.assertIsNone(at_head(other, directory))

    def test_outside_a_repository_there_is_none(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test_invoice.py"
            path.write_text(COMMITTED)
            self.assertIsNone(at_head(path, directory))


class TestTheDraftExemption(unittest.TestCase):
    def test_reshaping_an_assertion_you_never_committed_is_not_a_weakening(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _repository(directory, "test_invoice.py", COMMITTED)
            path.write_text(DRAFTED)
            verdict = _verdict(path, DRAFT_WEAKENED)
            self.assertEqual(
                [f.rule for f in verdict.findings if f.rule == "assertion_monotonicity"], [])
            self.assertFalse(blocks(verdict, None))

    def test_weakening_a_committed_assertion_still_blocks(self):
        """The protection is unchanged for everything actually committed."""
        with tempfile.TemporaryDirectory() as directory:
            path = _repository(directory, "test_invoice.py", COMMITTED)
            verdict = _verdict(path, COMMITTED_WEAKENED)
            self.assertIn("assertion_monotonicity", {f.rule for f in verdict.findings})
            self.assertTrue(blocks(verdict, None))

    def test_a_brand_new_test_file_is_not_exempt(self):
        """Writing a strong test, watching it fail, then weakening it is the
        tampering this rule exists to catch — and those tests are usually new.
        Exempting every uncommitted file would put a hole through the middle."""
        with tempfile.TemporaryDirectory() as directory:
            _repository(directory, "test_invoice.py", COMMITTED)
            fresh = Path(directory) / "test_fresh.py"
            fresh.write_text(COMMITTED)
            verdict = _verdict(fresh, COMMITTED_WEAKENED)
            self.assertIn("assertion_monotonicity", {f.rule for f in verdict.findings})
            self.assertTrue(blocks(verdict, None))

    def test_outside_a_repository_nothing_is_exempt(self):
        """No committed state to consult means no grounds to excuse anything."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test_invoice.py"
            path.write_text(COMMITTED)
            verdict = _verdict(path, COMMITTED_WEAKENED)
            self.assertIn("assertion_monotonicity", {f.rule for f in verdict.findings})


if __name__ == "__main__":
    unittest.main()
