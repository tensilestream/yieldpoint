"""Which revision a change is measured from, and saying so.

Attribution is only as good as the thing compared against. Against the working
tree's parent, a finding means "this edit made it worse"; against a branch's
merge base, the same finding means "this branch makes it worse". Same command,
different answer — so the basis is reported rather than assumed.
"""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from yieldpoint.basis import Basis, default_branch, resolve


def _git(args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, check=False)


def _repo(branch="main"):
    root = Path(tempfile.mkdtemp())
    _git(["init", "-q", "-b", branch, "."], root)
    _git(["config", "user.email", "t@t"], root)
    _git(["config", "user.name", "T"], root)
    (root / "a.py").write_text("x = 1\n")
    _git(["add", "-A"], root)
    _git(["commit", "-qm", "base"], root)
    return root


class TestResolve(unittest.TestCase):
    def test_an_explicit_revision_is_used_as_given(self):
        basis = resolve(".", "release-1")
        self.assertEqual(basis.revision, "release-1")
        self.assertIn("command line", basis.how)

    def test_nothing_asked_for_is_not_a_request_to_guess(self):
        """Empty means the working tree's parent, which is a real answer."""
        basis = resolve(".")
        self.assertIs(basis.known, False)
        self.assertEqual(basis.revision, "")

    def test_auto_asks_for_detection_explicitly(self):
        self.assertEqual(resolve(_repo(), "auto").revision, "main")


class TestDetection(unittest.TestCase):
    def test_a_conventional_branch_is_found_when_nothing_declares_one(self):
        basis = default_branch(_repo("main"))
        self.assertEqual(basis.revision, "main")
        self.assertIn("conventional", basis.how)

    def test_master_is_found_too(self):
        self.assertEqual(default_branch(_repo("master")).revision, "master")

    def test_an_unconventional_trunk_is_not_invented(self):
        """Better to resolve nothing than to compare against the wrong trunk."""
        self.assertEqual(default_branch(_repo("develop")).revision, "")

    def test_outside_a_repository_nothing_is_resolved(self):
        self.assertEqual(default_branch(tempfile.mkdtemp()).revision, "")


class TestItAlwaysSaysWhichOne(unittest.TestCase):
    def test_a_resolved_basis_names_the_revision_and_the_source(self):
        described = Basis("origin/main", "the remote's default branch").describe()
        self.assertIn("origin/main", described)
        self.assertIn("remote", described)

    def test_an_unresolved_basis_says_what_it_fell_back_to(self):
        """Silence would let every finding be attributed to the wrong change."""
        described = Basis().describe()
        self.assertIn("working tree's parent", described)
        self.assertIn("per edit, not per branch", described)


class TestAttributionAcrossABranch(unittest.TestCase):
    def test_a_branch_that_grows_a_long_file_is_told_what_it_added(self):
        """The reviewed scenario: one line added to a file already over the limit."""
        from yieldpoint.verify import verify_diff
        from yieldpoint.worktree import uncommitted

        root = _repo()
        (root / ".yieldpoint.json").write_text(
            json.dumps({"structure": {"max_file_lines": 300}}))
        (root / "big.py").write_text("\n".join(f"x{i} = 1" for i in range(400)) + "\n")
        _git(["add", "-A"], root)
        _git(["commit", "-qm", "big"], root)
        _git(["checkout", "-qb", "feature"], root)
        (root / "big.py").write_text((root / "big.py").read_text() + "y = 2\n")
        _git(["commit", "-qam", "one more"], root)

        basis = resolve(root, "auto")
        diff = uncommitted(root, against=basis.revision)
        verdict = verify_diff(diff.text, root=str(root),
                              policy=str(root / ".yieldpoint.json"))
        lengths = [f for f in verdict.findings if f.rule == "file_too_long"]
        self.assertEqual(len(lengths), 1)
        self.assertIn("400", lengths[0].detail)
        self.assertIn("401", lengths[0].detail)


if __name__ == "__main__":
    unittest.main()
