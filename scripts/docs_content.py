"""Prose for the documentation site.

Split from ``build_docs.py`` because the two change for different reasons: that
file is how the site is assembled and checked against the engine, this one is
what the site says. Keeping them together makes every wording fix look like a
change to the build.
"""

from __future__ import annotations

REPO = "https://github.com/tensilestream/yieldpoint"


def index_page() -> str:
    return """<section class="hero">
  <h1>Proves an AI-authored change didn't pass by weakening the tests.</h1>
  <p class="lede">The <strong>yield point</strong> is where a material stops springing
     back and deforms for good &mdash; the moment it quietly stops being as strong as it
     was. A test suite does the same under an agent's edits.</p>
  <pre class="diff"><code><span class="del">- assert invoice.total == Decimal("42.00")</span>
<span class="add">+ assert invoice.total is not None</span></code></pre>
  <p>The suite is green. Coverage is unchanged &mdash; the weaker assertion executes the
     same lines. The linter is silent. Nothing in a normal toolchain reports this, because
     every tool in it grades the code <em>as it now stands</em>, and this is a statement
     about what was <strong>taken away</strong>.</p>
  <p>Yieldpoint grades the <strong>transition</strong>. Deterministically, with no model
     call, and with the same answer on every machine.</p>
  <div class="cta">
    <a class="button" href="start.html">Get started</a>
    <a class="button ghost" href="rules.html">See the rules</a>
  </div>
</section>

<section class="grid3">
  <article><h3>No model call</h3><p>The critique is assembled from the diff, not
    generated. Zero tokens, milliseconds, and byte-identical on every machine &mdash;
    which is what makes it safe to gate a pipeline on.</p></article>
  <article><h3>No network, no dependencies</h3><p>The verification core has zero runtime
    dependencies and opens no socket. The whole supply chain can be audited in one
    sitting.</p></article>
  <article><h3>Never a false pass</h3><p>A change nothing could analyse returns
    <code>unverified</code> and exit code <code>3</code> &mdash; not <code>pass</code>.
    Silence is never mistaken for safety.</p></article>
</section>

<section>
  <h2>Two commands</h2>
  <pre><code>pip install yieldpoint
yieldpoint init      <span class="c"># config, MCP server and editor hook</span>
yieldpoint review    <span class="c"># what you have already broken</span></code></pre>
</section>
"""


# yieldpoint: allow function_too_long - a page of prose, not a procedure. "Extract the distinct steps" has no meaning for one HTML literal, and splitting it would hide the page from anyone editing the words.
def start_page() -> str:
    return """<h1>Getting started</h1>
<p class="lede">Two commands to install, one to find out whether the change you just
made took something away.</p>

<h2>Install</h2>
<pre><code>pip install yieldpoint            <span class="c"># zero runtime dependencies</span>
pipx install yieldpoint           <span class="c"># isolated CLI</span>
uv tool install yieldpoint        <span class="c"># same, via uv</span></code></pre>
<p>Python 3.10 or newer, and nothing else.</p>

<h2>Try it without installing anything</h2>
<pre><code>uvx yieldpoint review</code></pre>
<p>Run that in any repository with uncommitted work. It reads your diff from git,
including unstaged files, and tells you whether anything you changed weakens what the
tests verify.</p>

<h2>Set it up properly</h2>
<pre><code>yieldpoint init</code></pre>
<p><code>init</code> writes three files and backs up anything it touches:</p>
<table>
<tr><th>File</th><th>What it does</th></tr>
<tr><td><code>.yieldpoint.json</code></td><td>The rules. Committed, so the team shares one definition.</td></tr>
<tr><td><code>.mcp.json</code></td><td>Registers the MCP server, so your agent can <em>ask</em> what a rule means.</td></tr>
<tr><td><code>.claude/settings.json</code></td><td>Registers the hook, which is the part that actually <em>enforces</em>.</td></tr>
</table>

<div class="warn">
  <h3>Restart your editor after <code>init</code></h3>
  <p>Hooks and MCP servers are read when a session starts, so nothing you install is
  active in the session you install it from &mdash; and that looks exactly like it
  working: no output, no error, every edit allowed. <code>yieldpoint doctor</code>
  reports whether the hook has actually seen an edit, which is the only way to tell
  those two states apart. <code>yieldpoint review</code> works immediately, with no
  restart.</p>
</div>

<h2>It starts advisory</h2>
<p>The hook reports and never blocks. Run <code>yieldpoint init --enforce</code> once you
are happy with what it reports.</p>

<h2>Reading a verdict</h2>
<pre><code>$ yieldpoint review
REPAIR  1 finding(s)

  tests/test_invoice.py:14 in test_total  [assertion_monotonicity]
    Assertion on invoice.total was weakened: eq -&gt; non_null.
    fix: Re-assert invoice.total at eq strength, or fix the code under test so the
         original assertion passes. Restore `assert invoice.total == 42`.</code></pre>
<p>Every verdict carries a prescription naming exactly what to restore, so a rejected
change does not have to be diagnosed by guessing.</p>

<h2>Exit codes</h2>
<table>
<tr><th>Code</th><th>Meaning</th></tr>
<tr><td><code>0</code></td><td>Checked, and nothing was weakened.</td></tr>
<tr><td><code>1</code></td><td>Findings. Something was taken away.</td></tr>
<tr><td><code>2</code></td><td>The tool itself failed.</td></tr>
<tr><td><code>3</code></td><td><strong>Nothing could be analysed.</strong> Not a pass.</td></tr>
</table>
"""


def config_page() -> str:
    return """<h1>Configuration</h1>
<p class="lede">Everything that decides anything lives in <code>.yieldpoint.json</code>,
committed, so a team tunes it in review rather than forking the tool.</p>

<h2>A minimal file</h2>
<pre><code>{
  "project": "billing-service",
  "test_contract": {
    "protected_patterns": ["tests/**"],
    "assertion_monotonicity": "repair"
  },
  "structure": { "severity": "advisory", "max_file_lines": 300 },
  "metrics": { "enabled": true }
}</code></pre>

<h2>Sections</h2>
<table>
<tr><th>Section</th><th>Decides</th></tr>
<tr><td><code>test_contract</code></td><td>Which paths are protected, and how hard each contract rule bites.</td></tr>
<tr><td><code>structure</code></td><td>Size and shape limits. Reported, but do not fail a run unless <code>gates</code> is true.</td></tr>
<tr><td><code>refactor</code></td><td>Dangling references and removed exports.</td></tr>
<tr><td><code>boundaries</code></td><td>Layer zones, and what may import what.</td></tr>
<tr><td><code>ci</code></td><td>Whether removing or disabling a CI step is reported.</td></tr>
<tr><td><code>routing</code></td><td>How churn, complexity and importance escalate a verdict.</td></tr>
<tr><td><code>loop_breaker</code></td><td>When an agent is going round without making progress.</td></tr>
<tr><td><code>generated</code></td><td>How generated files are detected, and what a hand-edit means.</td></tr>
<tr><td><code>linters</code></td><td>Optional external linters. Off by default, curated argv only.</td></tr>
<tr><td><code>metrics</code></td><td>Local accounting, and your token price for the cost estimate.</td></tr>
<tr><td><code>voice</code></td><td>What gets spoken aloud, for voice-driven sessions.</td></tr>
<tr><td><code>scan</code></td><td>What a repository audit ignores.</td></tr>
</table>
<p>An unknown section or key is <strong>reported as a warning</strong>, never ignored
silently &mdash; believing you configured something while a default quietly applies is
worse than a wrong value.</p>

<h2>What stops a commit</h2>
<p>A finding that says something was <em>taken away</em> fails the run. A finding that
describes the <em>shape</em> of the code does not &mdash; it is printed, counted, and
visible in <code>scan</code>, but it does not stand between you and a commit.</p>
<pre><code>$ yieldpoint review
REPAIR  1 finding(s)

  22 files:0  [change_too_large]
    This change adds 1472 lines across 22 files, over the limit of 1200.

→ Reported, not blocking. These describe shape, not a weakening.
  Set structure.gates true in .yieldpoint.json to make them binding.</code></pre>
<p>The reasoning is about what happens next rather than about severity: a gate that
fires on ordinary days gets passed <code>--no-verify</code> out of habit, and the habit
does not distinguish a long function from a deleted assertion.</p>

<h2>Severities</h2>
<p>Every rule resolves to one of these, and the CLI's exit code follows the worst one.
There is no "advisory" severity: a finding either has a status that fails the run or the
rule is <code>off</code>. The editor hook is separately installable in an advisory mode
that reports without blocking, which is a property of that surface, not of a rule.</p>
<table>
<tr><th>Severity</th><th>Means</th></tr>
<tr><td><code>off</code></td><td>Not evaluated at all.</td></tr>
<tr><td><code>repair</code></td><td>The agent can fix this itself; hand it back the prescription.</td></tr>
<tr><td><code>escalate</code></td><td>A person needs to look. Retrying will not help.</td></tr>
<tr><td><code>block</code></td><td>Do not apply, do not retry. Reserved for rules with a measured false-positive rate.</td></tr>
</table>
"""


# yieldpoint: allow function_too_long - a page of prose, not a procedure. "Extract the distinct steps" has no meaning for one HTML literal, and splitting it would hide the page from anyone editing the words.
def integrations_page() -> str:
    return """<h1>Integrations</h1>
<p class="lede">One engine, several doors. Each answers the same question at a different
moment in the loop.</p>

<h2>Editor hook &mdash; the enforcing half</h2>
<p>Runs before an agent's edit lands, and can refuse it. This is the only surface that
prevents a weakening rather than reporting one afterwards.</p>
<pre><code>yieldpoint install-hook --advisory   <span class="c"># reports only</span>
yieldpoint install-hook --enforce    <span class="c"># blocks</span></code></pre>

<h2>MCP server &mdash; so the agent can ask</h2>
<p>Registers seven tools, including a zero-argument <code>yieldpoint_review</code> the
agent can call after finishing a set of edits.</p>
<pre><code>yieldpoint install-mcp --client cursor</code></pre>

<h2>Pre-commit</h2>
<pre><code>repos:
  - repo: https://github.com/tensilestream/yieldpoint
    rev: v0.1.1
    hooks:
      - id: yieldpoint</code></pre>
<p>The hook runs <code>review --staged</code>, which asks git for the staged diff itself.
Do not use <code>check --diff -</code> here: pre-commit gives a hook no stdin, so it reads
an empty diff and reports <code>ok</code> on everything.</p>

<h2>CI</h2>
<pre><code>- run: pip install yieldpoint
- run: yieldpoint review --against origin/main --json</code></pre>
<p>Exit <code>1</code> on findings, <code>3</code> when nothing could be analysed. Treat
<code>3</code> as a failure in any pipeline that matters: it means the gate did not run,
which is not the same as passing.</p>

<h2>Agent frameworks</h2>
<p>A LangGraph adapter ships in the package, with a router that turns a verdict into an
edge. The <code>unverified</code> status has its own unmapped edge by default, so a graph
that never considered the case raises rather than quietly applying an unchecked change.</p>
<pre><code>from yieldpoint.langgraph import make_router

graph.add_conditional_edges("verify", make_router(on_unverified="escalate"))</code></pre>
<p>Runnable examples for plain loops, CrewAI, the OpenAI Agents SDK, fan-out and
long-running sessions are in <a href="%s/tree/main/examples">examples/</a>.</p>

<h2>Measuring it</h2>
<pre><code>yieldpoint stats              <span class="c"># totals, plus a per-turn timeline</span>
yieldpoint stats --html       <span class="c"># the same, as a page</span>
yieldpoint export             <span class="c"># the ledger as JSON Lines</span></code></pre>
<p>Recording is local only. To send it somewhere, name a command in
<code>YIELDPOINT_SINK</code> and Yieldpoint pipes each turn's events to its stdin &mdash;
it never opens a socket itself.</p>
""" % REPO


def limits_page() -> str:
    return """<h1>Status and limits</h1>
<p class="lede">Alpha. The engine, CLI, hook, MCP server, LangGraph adapter, diff/CI path
and repository audit all work and are covered by the test suite. Read this before
adopting.</p>

<div class="warn">
<h3>Python only</h3>
<p>TypeScript and Java are designed but not built. Other languages are never silently
passed &mdash; a change nothing could analyse returns <code>unverified</code> and exits
<code>3</code>. If your agent writes TypeScript, this will tell you honestly that it
checked nothing, which is useful but is not the product you want yet.</p>
</div>

<h2>Where it is weak</h2>
<ul>
<li><strong>Snapshot, property-based and heavily table-driven suites</strong> are poorly
served. Counting assertions is not meaningful there.</li>
<li><strong>Assertions in an imported helper are invisible.</strong> Helpers in the same
module are read through, including helper-calling-helper chains. A helper imported from
another module is not expanded and its assertions are not counted.</li>
<li><strong>Decomposing a dict comparison into per-field assertions is deliberately
allowed</strong>, even though it drops the implicit "and no other keys" check. That trade
and its reasoning are written out in the source.</li>
</ul>

<h2>What is not claimed</h2>
<p>That your agent converges in fewer <em>total</em> model calls. That the prescription
costs zero model calls is a property of the architecture and holds. That repair loops
therefore converge faster against a real model has not been benchmarked, and is not
claimed.</p>
<p>No performance figure appears anywhere in this project without a runnable benchmark
behind it.</p>

<h2>Why not a tool that already exists</h2>
<table>
<tr><th>You already have</th><th>Does it catch an agent weakening a test?</th></tr>
<tr><td>Coverage</td><td><strong>No</strong> &mdash; and worse than neutral. Delete an assertion and coverage is unchanged; delete a failing test and it goes <em>up</em>.</td></tr>
<tr><td>Linters</td><td><strong>No.</strong> <code>assert x == 42</code> and <code>assert x</code> are both clean code. Nothing in a linter reads the previous version of the file.</td></tr>
<tr><td>Mutation testing</td><td><strong>Yes, in principle</strong> &mdash; it is the rigorous answer. It also needs minutes to hours, so it cannot sit between generate and apply. Use both, at different points.</td></tr>
<tr><td>Code review</td><td><strong>Sometimes.</strong> Not reliably, in a forty-file agent diff, on the fourth one that day.</td></tr>
<tr><td>LLM-as-judge</td><td><strong>Sometimes</strong>, at one model call per round and a verdict that changes between runs. You cannot gate a pipeline on a judge that flakes.</td></tr>
</table>
<p>Every one of those evaluates code as it now stands. "The agent cheated" is a statement
about what was <em>taken away</em>, and only a diff-native check can express it.</p>
"""
