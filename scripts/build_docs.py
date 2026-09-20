#!/usr/bin/env python3
"""Build the documentation site in ``docs/``.

Two jobs, and the second is the point. It renders the pages, and it **checks
them against the engine**: every rule the code can emit must appear in the rules
reference, and every rule in the reference must exist in the code. Documentation
that drifts is worse than none, because people act on it — so the drift is a
build failure here and a test failure in CI, rather than something a reader
discovers.

    python3 scripts/build_docs.py          # write docs/
    python3 scripts/build_docs.py --check  # verify only, change nothing

No dependencies, like everything else in this repository.
"""

from __future__ import annotations

import argparse
import ast
import html
import pathlib
import re
import sys

# Same directory, which Python puts on the path for a script it is running.
from docs_content import (
    config_page, index_page, integrations_page, limits_page, start_page,
)
from docs_style import STYLE

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "docs"
REPO = "https://github.com/tensilestream/yieldpoint"
SITE = "https://tensilestream.github.io/yieldpoint"

#: A module-level ``UPPER_SNAKE = "lower_snake"`` in the package is a rule id.
_RULE_VALUE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)+$")

#: Constants that match the shape but are not rules. Listed rather than
#: pattern-matched away, so that promoting one to a real rule fails the check
#: instead of silently skipping it.
NOT_RULES = {
    "test_removed": "a weakening kind reported under assertion_monotonicity",
    "yieldpoint_attempts": "a LangGraph state key",
    "yieldpoint_history": "a LangGraph state key",
    "yieldpoint_loop_tripped": "a LangGraph state key",
}


def _rule_id(node: ast.Assign) -> str:
    """The rule id this assignment defines, or "" if it is not one."""
    target, value = node.targets[0], node.value
    if not (isinstance(target, ast.Name) and target.id.isupper()):
        return ""
    if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
        return ""
    if not _RULE_VALUE.match(value.value) or value.value in NOT_RULES:
        return ""
    return value.value


def emitted_rules() -> dict[str, str]:
    """Every rule id the engine can produce, mapped to where it is defined."""
    found: dict[str, str] = {}
    for path in sorted((ROOT / "yieldpoint").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            rule = _rule_id(node)
            if rule:
                found[rule] = str(path.relative_to(ROOT))
    return found


# --------------------------------------------------------------------------
# The rules reference. Prose lives here; the ids are checked against the code.
# --------------------------------------------------------------------------

CONTRACT = "contract"
REFACTOR = "refactor"
STRUCTURE = "structure"
PIPELINE = "pipeline"

GROUPS = {
    CONTRACT: ("What the tests verify",
               "The reason this project exists. Each of these is a statement about "
               "what a change <em>took away</em>, which is why no tool that grades "
               "the end state can report them."),
    REFACTOR: ("Moves that did not land",
               "A refactor is only correct if everything that pointed at the old "
               "thing now points at the new one. These catch the half-finished move."),
    PIPELINE: ("The pipeline itself",
               "The cheapest way to make a suite pass is to stop running it. These "
               "watch the machinery rather than the code."),
    STRUCTURE: ("Shape and size",
               "Maintainability, not correctness. These are <strong>reported but do "
               "not fail a run</strong>: a commit refused because a function is "
               "fifty-one lines teaches people to reach for <code>--no-verify</code>, "
               "and that habit mutes the rules that matter too. Set "
               "<code>structure.gates</code> true to make them binding."),
}

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
    "duplicate_implementation": (STRUCTURE, "repair", "Structurally identical code",
        "Two functions with the same shape. Two copies drift apart, and a fix applied "
        "to one is a bug left in the other."),
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


def check_rules() -> list[str]:
    """Complaints about the rules page, or an empty list."""
    engine, documented = emitted_rules(), set(RULES)
    problems = []
    for rule in sorted(set(engine) - documented):
        problems.append(f"{rule} is emitted by {engine[rule]} but is not in the docs")
    for rule in sorted(documented - set(engine)):
        problems.append(f"{rule} is documented but no core module defines it")
    return problems


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

PAGES = ("index", "start", "rules", "config", "integrations", "limits")
TITLES = {
    "index": "Yieldpoint",
    "start": "Getting started",
    "rules": "Rules reference",
    "config": "Configuration",
    "integrations": "Integrations",
    "limits": "Status and limits",
}

DESCRIPTIONS = {
    "index": "Yieldpoint deterministically detects when AI coding agents weaken tests, remove safeguards, or bypass CI.",
    "start": "Install Yieldpoint in a Python repository and block AI-authored changes that weaken tests or safeguards.",
    "rules": "Reference for Yieldpoint's deterministic rules for weakened assertions, skipped tests, CI bypasses, and risky refactors.",
    "config": "Configure Yieldpoint's repository policy for test contracts, refactors, CI safeguards, and code structure.",
    "integrations": "Use Yieldpoint with Claude Code, Cursor, Codex, MCP, pre-commit, and CI to verify AI-authored code changes.",
    "limits": "Yieldpoint support status, current limitations, and the safeguards it can verify in Python repositories.",
}


def page_url(page: str) -> str:
    """Return the canonical public URL for one generated page."""
    return f"{SITE}/" if page == "index" else f"{SITE}/{page}.html"


def shell(page: str, body: str) -> str:
    nav = "".join(
        f'<a class="{"on" if p == page else ""}" href="{"index" if p == "index" else p}.html">'
        f"{html.escape(TITLES[p])}</a>"
        for p in PAGES
    )
    title = TITLES[page] if page != "index" else "Yieldpoint"
    suffix = "" if page == "index" else " · Yieldpoint"
    full_title = f"{title}{suffix}"
    url = page_url(page)
    description = DESCRIPTIONS[page]
    structured_data = ""
    if page == "index":
        structured_data = f'''\n<script type="application/ld+json">\n{{\n  "@context": "https://schema.org",\n  "@type": "SoftwareApplication",\n  "name": "Yieldpoint",\n  "applicationCategory": "DeveloperApplication",\n  "operatingSystem": "Cross-platform",\n  "description": "{DESCRIPTIONS["index"]}",\n  "url": "{SITE}/",\n  "codeRepository": "{REPO}",\n  "downloadUrl": "https://pypi.org/project/yieldpoint/",\n  "programmingLanguage": "Python"\n}}\n</script>'''
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(full_title)}</title>
<meta name="description" content="{html.escape(description, quote=True)}">
<link rel="canonical" href="{url}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Yieldpoint">
<meta property="og:title" content="{html.escape(full_title, quote=True)}">
<meta property="og:description" content="{html.escape(description, quote=True)}">
<meta property="og:url" content="{url}">
<meta name="twitter:card" content="summary">
<meta name="twitter:title" content="{html.escape(full_title, quote=True)}">
<meta name="twitter:description" content="{html.escape(description, quote=True)}">{structured_data}
<link rel="stylesheet" href="style.css">
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<header class="top">
  <a class="brand" href="index.html">
    <span class="mark" aria-hidden="true">&#9581;&#9679;&#9582;</span>
    <span>Yieldpoint</span>
  </a>
  <nav>{nav}<a class="out" href="{REPO}">GitHub &#8599;</a></nav>
</header>
<main id="main">
{body}
</main>
<footer>
  <p>Apache-2.0. The name and mark are not licensed with the code &mdash;
     see <a href="{REPO}/blob/main/TRADEMARK.md">TRADEMARK.md</a>.</p>
  <p>This page is generated by <code>scripts/build_docs.py</code>; the rules
     reference is checked against the engine on every build.</p>
</footer>
</body>
</html>
"""


def rules_page() -> str:
    out = ["<h1>Rules reference</h1>",
           "<p class='lede'>Every rule the engine can emit. This page is generated "
           "from the code: a rule that exists but is undocumented, or documented but "
           "removed, fails the build and the test suite.</p>"]
    for group, (heading, blurb) in GROUPS.items():
        out.append(f"<section><h2>{html.escape(heading)}</h2><p class='blurb'>{blurb}</p>")
        out.append("<div class='rules'>")
        for rule, (grp, severity, title, detail) in sorted(RULES.items()):
            if grp != group:
                continue
            out.append(
                f"<article id='{rule}'><div class='rh'>"
                f"<code class='rid'>{rule}</code>"
                f"<span class='sev sev-{severity}'>{severity}</span></div>"
                f"<h3>{html.escape(title)}</h3><p>{detail}</p></article>")
        out.append("</div></section>")
    out.append(
        "<section><h2>Answering a rule</h2><p class='blurb'>Every rule is sometimes "
        "right about the code and wrong about the intent. Say so in the source, with a "
        "reason, and the finding is suppressed for that line only &mdash; and counted, "
        "so suppression cannot rot quietly.</p>"
        "<pre><code># yieldpoint: allow assertion_monotonicity - broadened to cover "
        "YAML clients\ndef test_every_client_resolves_a_path():\n    ...</code></pre>"
        "<p>One rule per comment, a reason required, and the comment must sit on the "
        "line the finding points at or within two lines above it.</p></section>")
    return "\n".join(out)


def build() -> None:
    OUT.mkdir(exist_ok=True)
    (OUT / ".nojekyll").write_text("", encoding="utf-8")
    (OUT / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\n\nSitemap: {SITE}/sitemap.xml\n",
        encoding="utf-8",
    )
    urls = "\n".join(
        f"  <url><loc>{page_url(page)}</loc></url>" for page in PAGES
    )
    (OUT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{urls}\n"
        "</urlset>\n",
        encoding="utf-8",
    )
    (OUT / "style.css").write_text(STYLE, encoding="utf-8")
    bodies = {
        "index": index_page(), "start": start_page(), "rules": rules_page(),
        "config": config_page(), "integrations": integrations_page(),
        "limits": limits_page(),
    }
    for page, body in bodies.items():
        (OUT / f"{page}.html").write_text(shell(page, body), encoding="utf-8")
    print(f"wrote {len(bodies) + 4} files to {OUT.relative_to(ROOT)}/")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="verify the rules reference against the engine, write nothing")
    args = parser.parse_args()

    problems = check_rules()
    if problems:
        for problem in problems:
            print(f"docs: {problem}", file=sys.stderr)
        print(f"\n{len(problems)} rule(s) out of step. Edit RULES in "
              "scripts/build_docs.py.", file=sys.stderr)
        return 1
    print(f"rules reference covers all {len(RULES)} rules the engine can emit")
    if not args.check:
        build()
    return 0


if __name__ == "__main__":
    sys.exit(main())
