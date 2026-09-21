"""Every rule the engine can emit, as prose for the documentation site.

Split from build_docs.py because this file grows by one entry every time
Yieldpoint learns a rule, and that file changes only when the site's shape
does. Keeping them together meant the builder got longer forever for reasons
that had nothing to do with building.

Checked against the engine by ``build_docs.py --check``, so a rule cannot ship
undocumented.
"""

from __future__ import annotations

CONTRACT = "contract"
REFACTOR = "refactor"
STRUCTURE = "structure"
PIPELINE = "pipeline"

RULES = {
    "assertion_monotonicity": (CONTRACT, "repair", "Assertion weakened",
        "An assertion on some value got weaker: <code>== 42</code> became "
        "<code>is not None</code>, a specific exception became a bare "
        "<code>Exception</code>, an exact count became a lower bound. The subject is "
        "still asserted, so the test still passes and coverage is unchanged."),
    "vacuous_assertion": (CONTRACT, "repair", "Assertion that cannot fail",
        "<code>assert True</code>, <code>assert [1]</code>, <code>assert x or True</code> "
        "— an assertion whose truth does not depend on the code under test."),
    "weak_new_test": (CONTRACT, "repair", "New test that only checks existence",
        "A test added by this change whose every assertion is a not-null or truthiness "
        "check. Monotonicity cannot see this — there is no earlier version to be weaker "
        "than — yet the test passes whatever value the code returns. This is the shape "
        "an agent produces when asked to add a feature <em>with tests</em>. Advisory by "
        "default: a smoke test that asserts a call returns something is legitimate."),
    "empty_test": (CONTRACT, "repair", "Test with nothing left in it",
        "A test function whose body asserts nothing: a <code>pass</code>, a docstring, "
        "or setup with no check at the end. It runs, it is counted, it verifies nothing."),
    "skip_marker": (CONTRACT, "repair", "Test newly skipped",
        "A <code>@skip</code>, <code>@skipif</code>, <code>@xfail</code> or equivalent "
        "added to a test that did not have one. The suite goes green by not asking."),
    "disabled_assertion": (CONTRACT, "repair", "Assertion commented out or neutered",
        "An assertion still present in the source but no longer executed — commented "
        "out, moved behind a condition that is never true, or swallowed by a bare "
        "<code>except</code>."),
    "dangling_reference": (REFACTOR, "repair", "Reference to something that moved",
        "A name is gone and something still points at it. The classic half-finished "
        "rename, where the tests that happen not to exercise that path stay green."),
    "export_removed": (REFACTOR, "repair", "Public API removed",
        "A name that was part of a module's public surface — in <code>__all__</code>, "
        "or imported elsewhere — is no longer there. Callers outside the change set "
        "cannot be seen by a diff, so this asks rather than assumes."),
    "boundary_violation": (REFACTOR, "repair", "Layer boundary crossed",
        "An import that the project's declared zones forbid. Configured in "
        "<code>.yieldpoint.json</code>; mature tools exist for this, and it ships here "
        "for convenience rather than as a reason to adopt."),
    "ci_check_removed": (PIPELINE, "escalate", "CI step deleted",
        "A step disappeared from a workflow file. Deleting the job that runs the tests "
        "is the most effective way to make the tests pass."),
    "ci_check_disabled": (PIPELINE, "escalate", "CI step neutralised",
        "A step is still there but can no longer fail: <code>|| true</code>, "
        "<code>continue-on-error</code>, <code>if: false</code>. Reported as disabling "
        "the same step rather than as a removal plus an addition."),
    "file_too_long": (STRUCTURE, "repair", "File over the line limit",
        "Default 300 lines of code, excluding blanks and comments."),
    "function_too_long": (STRUCTURE, "repair", "Function over the line limit",
        "Default 50 lines."),
    "too_many_parameters": (STRUCTURE, "repair", "Too many parameters",
        "Default 5."),
    "nesting_too_deep": (STRUCTURE, "repair", "Nesting too deep",
        "Default 4 levels."),
    "complexity_too_high": (STRUCTURE, "repair", "Too many branches",
        "Default 10."),
    "duplicate_across_files": (STRUCTURE, "repair", "The same implementation in two files",
        "A function structurally identical to one in another file changed by the same "
        "commit. Shape is compared, not text, so a copy-paste that renamed its "
        "variables is still found. The within-file case belongs to "
        "<code>duplicate_implementation</code>; this is the one neither reader can see."),
    "swallowed_exception": (REFACTOR, "repair",
        "A handler that catches everything and records nothing",
        "A <code>try</code> block gained <code>except Exception: pass</code> "
        "&mdash; or a bare <code>except:</code>, or one whose body is only "
        "<code>...</code>, <code>continue</code> or a bare <code>return</code>. "
        "Every failure on that path now looks like success, so a test covering "
        "it keeps passing while verifying nothing. Naming the exception you "
        "expect, logging, or re-raising are all fine; only silent breadth is "
        "reported, and only when this change introduced it."),
    "out_of_scope_edit": (PIPELINE, "repair",
        "A file outside what this task said it would touch",
        "Declared with <code>yieldpoint task --touch</code>. The only rule here "
        "that knows something the code cannot tell it: every other rule reads "
        "the source and concludes, this one compares what changed against what "
        "somebody said would change. <strong>Reported, never enforced</strong> "
        "&mdash; intent legitimately changes mid-task; what must not happen is "
        "the drift going unnoticed until review."),
    "new_file_out_of_scope": (PIPELINE, "repair",
        "A new file, in a task that said it would add none",
        "The same contract, for <code>--no-new-files</code>. Aimed at the "
        "habit of answering a question with a new module rather than the one "
        "that already covers the concern."),
    "policy_weakened": (PIPELINE, "repair", "The rules themselves were loosened",
        "A limit raised, a severity lowered, a rule switched off, a path added to "
        "the exclusions, or the ledger disabled. Raising a threshold until a finding "
        "disappears is the same act as weakening a test until it passes &mdash; only "
        "the file being edited differs. <strong>Reported and never enforced</strong>, "
        "whatever <code>structure.gates</code> says: a project must be able to change "
        "its own standards without first defeating the tool that holds them."),
    "duplicate_implementation": (STRUCTURE, "repair", "Structurally identical code",
        "Two functions with the same shape. Two copies drift apart, and a fix applied "
        "to one is a bug left in the other."),
    "sibling_module_shadows_package": (STRUCTURE, "repair",
        "New module named as a package it is not in",
        "A new <code>foo_bar.py</code> written beside an existing "
        "<code>foo/</code> package. The name says the code belongs to that "
        "package; the filesystem says it does not. Characteristic of code "
        "written by something that can see the file it is creating but not the "
        "directory it is creating it in. Only new files are reported."),
    "utility_module": (STRUCTURE, "repair", "Module with no theme",
        "A <code>utils</code>-shaped file: unrelated functions with nothing in common "
        "but the fact that nobody knew where else to put them."),
    "change_too_large": (STRUCTURE, "repair", "Change too large to review",
        "Added lines past the configured ceiling. Aimed at agents, which do not tire "
        "and will happily produce a forty-file diff nobody can read."),
    "generated_file_edited": (STRUCTURE, "repair", "Generated file edited by hand",
        "A file marked as generated was edited directly. The edit is lost on the next "
        "regeneration, which is a bug that appears later and somewhere else."),
}

__all__ = ["RULES", "CONTRACT", "REFACTOR", "STRUCTURE", "PIPELINE"]
