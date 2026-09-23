"""Integration page prose, split so routing docs do not grow the base page module."""

from sdk_docs import adapters_section

REPO = "https://github.com/tensilestream/yieldpoint"


# yieldpoint: allow function_too_long - one prose page is intentionally kept as one reviewed literal.
def integrations_page() -> str:
    return """<h1>Integrations</h1>
<p class="lede">One engine, several doors. Each answers the same question at a different
moment in the loop.</p>

<h2>Editor hook &mdash; the enforcing half</h2>
<p>Runs before an agent's edit lands and can refuse it; this is the only surface that prevents a weakening rather than reporting one afterwards.</p>
<pre><code>yieldpoint install-hook --advisory   <span class="c"># reports only</span>
yieldpoint install-hook              <span class="c"># blocks (the default)</span></code></pre>

<h2>MCP server &mdash; so the agent can ask</h2>
<p>Registers eleven tools, including a zero-argument <code>yieldpoint_review</code> the
agent can call after finishing a set of edits.</p>
<pre><code>yieldpoint install-mcp --client cursor</code></pre>
<p>The three routing tools are advisory contracts: they build evidence, a bounded
handoff capsule and a handoff decision. They never choose a provider or send data.
Read the <a href="routing.html">routing guide</a> before enabling host automation.</p>

<h2>Pre-commit</h2>
<pre><code>repos:
  - repo: https://github.com/tensilestream/yieldpoint
    rev: v0.1.1
    hooks:
      - id: yieldpoint</code></pre>
<p>The hook runs <code>review --staged</code>, which asks git for the staged diff itself. Do not use <code>check --diff -</code> here: pre-commit gives a hook no stdin, so it reads an empty diff and reports <code>ok</code> on everything.</p>

<h2>CI</h2>
<pre><code>- run: pip install yieldpoint
- run: yieldpoint review --against origin/main --json</code></pre>
<p>Exit <code>1</code> on findings, <code>3</code> when nothing could be analysed. Treat <code>3</code> as a failure in any pipeline that matters: it means the gate did not run, which is not the same as passing.</p>

<h2>Agent frameworks</h2>
<p>A LangGraph adapter ships in the package, with a router that turns a verdict into an
edge. The <code>unverified</code> status has its own unmapped edge by default, so a graph
that never considered the case raises rather than quietly applying an unchecked change.</p>
<pre><code>from yieldpoint.langgraph import make_router

graph.add_conditional_edges("verify", make_router(on_unverified="escalate"))</code></pre>
<p>Runnable examples for plain loops, CrewAI, the OpenAI Agents SDK, fan-out and
long-running sessions are in <a href="%s/tree/main/examples">examples/</a>.</p>

%s

<h2>Measuring it</h2>
<pre><code>yieldpoint stats              <span class="c"># totals, plus a per-turn timeline</span>
yieldpoint stats --html       <span class="c"># the same, as a page</span>
yieldpoint export             <span class="c"># the ledger as JSON Lines</span></code></pre>
<p>Recording is local only. To send it somewhere, name a command in
<code>YIELDPOINT_SINK</code> and Yieldpoint pipes each turn's events to its stdin &mdash;
it never opens a socket itself.</p>
""" % (REPO, adapters_section(REPO))
