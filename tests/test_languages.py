"""How much of a repository this build can actually read.

From the review: *"If it only handles Python, it's a Python tool."* The useful
answer is not a matrix in a README, it is a number from the reader's own tree.
A repository is allowed to conclude this is not for it yet; that is a better
outcome than seeing `ok` on a change that touched nothing analysable.
"""

import tempfile
import unittest
from pathlib import Path

from yieldpoint.core.policy import Policy
from yieldpoint.languages import (
    CI_ONLY,
    FULL,
    NONE,
    depth_for,
    render,
    survey,
    to_dict,
)


def _tree(files):
    root = Path(tempfile.mkdtemp())
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text)
    return root


class TestDepth(unittest.TestCase):
    def test_python_gets_everything(self):
        self.assertEqual(depth_for("src/a.py", Policy()), FULL)

    def test_a_workflow_is_matched_by_path_not_extension(self):
        self.assertEqual(depth_for(".github/workflows/ci.yml", Policy()), CI_ONLY)

    def test_an_ordinary_yaml_file_is_not(self):
        self.assertEqual(depth_for("config/app.yml", Policy()), NONE)

    def test_typescript_gets_structure_rules_but_not_assertions(self):
        """Listing it as supported without that caveat would be the false
        green everything else here refuses."""
        from yieldpoint.core import typescript
        from yieldpoint.languages import NEEDS_PARSER, STRUCTURE_ONLY

        expected = STRUCTURE_ONLY if typescript.available() else NEEDS_PARSER
        self.assertEqual(depth_for("src/app.ts", Policy()), expected)

    def test_a_language_nothing_claims_is_not_evaluated(self):
        self.assertEqual(depth_for("src/main.go", Policy()), NONE)

    def test_without_the_parser_typescript_is_unevaluated_not_clean(self):
        """Depth is opt-in; silence is not."""
        from yieldpoint.languages import NEEDS_PARSER
        from unittest import mock

        with mock.patch("yieldpoint.core.typescript.available", return_value=False):
            self.assertEqual(depth_for("src/app.ts", Policy()), NEEDS_PARSER)


class TestSurvey(unittest.TestCase):
    def test_it_counts_languages_this_build_cannot_read(self):
        """The whole point. A survey that only sees what it covers reports
        100% on every repository ever — which is what the first version did,
        because it reused the walker that filters to analysable files."""
        root = _tree({"a.py": "x = 1\n", "b.rb": "x = 1\n",
                      "c.go": "package main\n"})
        found = {c.extension: c for c in survey(root, Policy())}
        self.assertEqual(found[".rb"].depth, NONE)
        self.assertEqual(found[".go"].depth, NONE)
        self.assertEqual(found[".py"].depth, FULL)

    def test_a_repository_with_no_python_is_not_reported_as_covered(self):
        root = _tree({"a.go": "package main\n", "b.go": "package x\n"})
        payload = to_dict(survey(root, Policy()))
        self.assertEqual(payload["analysed"], 0)
        self.assertEqual(payload["source_files"], 2)

    def test_documentation_does_not_count_against_coverage(self):
        """A repository is not less covered for containing a licence."""
        root = _tree({"a.py": "x = 1\n", "README.md": "hi\n", "d.json": "{}\n"})
        self.assertEqual(to_dict(survey(root, Policy()))["source_files"], 1)

    def test_the_tools_own_output_is_not_surveyed(self):
        """Otherwise a repository looks less covered the longer this has run."""
        root = _tree({"a.py": "x = 1\n", ".yieldpoint/metrics.jsonl": "{}\n",
                      ".yieldpoint/report.html": "<p>"})
        self.assertEqual(to_dict(survey(root, Policy()))["source_files"], 1)

    def test_files_with_no_extension_are_left_out_rather_than_counted_against(self):
        root = _tree({"a.py": "x = 1\n", "LICENSE": "MIT\n", "Makefile": "all:\n"})
        self.assertEqual(to_dict(survey(root, Policy()))["source_files"], 1)


class TestRender(unittest.TestCase):
    def _text(self, files):
        return render(survey(_tree(files), Policy()))

    def test_it_states_the_share_this_build_analyses(self):
        text = self._text({"a.py": "x = 1\n", "b.go": "package main\n"})
        self.assertIn("1 of 2 source files (50%)", text)

    def test_it_says_the_rest_are_never_reported_as_passing(self):
        text = self._text({"a.py": "x = 1\n", "b.go": "package main\n"})
        self.assertIn("never as a pass", text)

    def test_a_fully_covered_repository_omits_that_warning(self):
        self.assertNotIn("never as a pass", self._text({"a.py": "x = 1\n"}))

    def test_it_names_where_the_depth_stops_rather_than_implying_breadth(self):
        text = self._text({"a.py": "x = 1\n"})
        self.assertIn("only language whose *assertions* are checked", text)

    def test_one_line_per_extension_even_when_treated_differently(self):
        text = self._text({".github/workflows/ci.yml": "on: push\n",
                           "config/app.yml": "a: 1\n"})
        self.assertEqual(len([l for l in text.splitlines() if ".yml" in l]), 1)

    def test_an_empty_tree_says_so(self):
        self.assertIn("No source files", render([]))


if __name__ == "__main__":
    unittest.main()
