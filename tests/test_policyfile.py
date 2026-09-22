"""Nothing enforces a rule that no file in the repository states.

A field review reported being blocked by a 300-line limit in a repository with
no `.yieldpoint.json`, by a message telling them to change it in that file.
The limit was a default compiled into the tool, and the hook had been installed
without the config ever being written. These tests pin both halves shut.
"""

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from yieldpoint.core.policy import Policy
from yieldpoint.policyfile import FILENAME, ensure, locate, where


class TestEnsure(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_a_repository_without_a_policy_gets_one(self):
        written = ensure(self.root)
        self.assertTrue(written.created)
        self.assertEqual(written.path, self.root / FILENAME)
        # The file must be the policy, not merely a file: an installer that
        # writes something unreadable is the same failure with extra steps.
        raw = json.loads((self.root / FILENAME).read_text(encoding="utf-8"))
        self.assertEqual(raw["structure"]["max_lines"], 50)
        self.assertEqual(raw["metrics"]["path"], ".yieldpoint/metrics.jsonl")

    def test_running_twice_leaves_the_first_one_alone(self):
        ensure(self.root)
        before = (self.root / FILENAME).read_bytes()
        again = ensure(self.root)
        self.assertFalse(again.created)
        self.assertEqual((self.root / FILENAME).read_bytes(), before)

    def test_an_existing_policy_is_never_edited(self):
        """A config that exists is a decision somebody made."""
        (self.root / FILENAME).write_text('{"version": 1, "structure": {"max_lines": 9}}')
        ensure(self.root)
        self.assertEqual(Policy.load(str(self.root / FILENAME)).structure.max_lines, 9)

    def test_what_is_written_is_readable_by_the_policy_reader(self):
        ensure(self.root)
        policy = Policy.load(str(self.root / FILENAME))
        self.assertEqual(policy.structure.max_lines, 50)

    def test_an_unwritable_repository_is_reported_not_raised(self):
        """Refusing to install would trade a visible problem for a worse one."""
        with mock.patch.object(Path, "write_text", side_effect=OSError("Permission denied")):
            written = ensure(self.root)
        self.assertFalse(written.created)
        self.assertFalse(written.visible)
        self.assertIn("built-in defaults", written.describe())


class TestEveryLimitIsStated(unittest.TestCase):
    """The rule the review's session broke: an enforced number must be legible."""

    def test_the_written_policy_names_every_structural_limit_in_force(self):
        from dataclasses import fields

        from yieldpoint.core.policy import Structure
        from yieldpoint.starter import STARTER_CONFIG

        written = STARTER_CONFIG["structure"]
        limits = [f.name for f in fields(Structure()) if f.name.startswith("max_")]
        missing = [name for name in limits if name not in written]
        self.assertEqual(missing, [], "enforced but absent from the starter config")

    def test_metrics_says_it_writes_into_the_repository(self):
        """It is on by default and creates a directory nobody asked for."""
        from yieldpoint.starter import STARTER_CONFIG

        self.assertTrue(STARTER_CONFIG["metrics"]["enabled"])
        self.assertIn("repository", STARTER_CONFIG["metrics"]["_comment"])


class TestWhere(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_it_names_the_config_when_one_exists(self):
        ensure(self.root)
        self.assertIn(str(self.root / FILENAME), where(self.root))

    def test_it_never_names_a_path_that_does_not_resolve(self):
        """The exact defect reported: advice pointing at a file that is not there."""
        sentence = where(self.root)
        self.assertIsNone(locate(self.root))
        for word in sentence.replace(",", " ").split():
            if word.endswith(FILENAME) and word != FILENAME:
                self.fail(f"named a path that does not exist: {word}")
        self.assertIn("yieldpoint init", sentence)


class TestInstallHookWritesThePolicy(unittest.TestCase):
    def test_installing_the_gate_writes_what_it_gates_on(self):
        from yieldpoint.install import install_hook

        root = Path(tempfile.mkdtemp())

        class Args:
            settings = str(root / "settings.json")
            advisory = True
            no_report = True
            no_git = True
            compact = False

        Args.root = str(root)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            install_hook(Args())

        # The gate and the thing it gates on must arrive together, and the
        # config must be the one the reader will actually enforce.
        self.assertEqual(Policy.load(str(root / FILENAME)).structure.max_parameters, 5)
        self.assertIn("wrote", out.getvalue())


if __name__ == "__main__":
    unittest.main()
