"""Provider-neutral routing page kept separate from the established docs pages."""

REPO = "https://github.com/tensilestream/yieldpoint"


def routing_page() -> str:
    return """<h1>Safe model routing</h1>
<p class="lede">Yieldpoint can describe what a change needs without selecting a model or
calling a provider. Your host owns models, keys, vendor requests and final actions.</p>

<h2>Start observe-only</h2>
<pre><code>{
  "routing_session": {
    "enabled": true,
    "max_model_switches": 1,
    "capsule_max_chars": 12000,
    "router_overhead_fraction": 0.05
  }
}</code></pre>
<p>Enable this first in a non-enforcing integration. Compare the recommended tier with
the model that actually completed the task, then choose any provider policy outside
Yieldpoint. Do not use an uncalibrated confidence value as permission to act.</p>

<h2>One admission, one bounded handoff</h2>
<pre><code>yieldpoint assess-routing --path sdk/node/src/profile.js --after after.js
yieldpoint build-capsule --profile profile.json --session session.json \\
  --objective "Validate release routing" --acceptance "Node tests pass"
yieldpoint handoff-check --profile profile.json --session session.json \\
  --event verification_failed --capability strong_reasoning --capability tool_use</code></pre>
<p>Keep the admitted model for normal work. A handoff is allowed only at an explicit
checkpoint, only within the switch and overhead budgets, and only when the candidate
has the profile&rsquo;s required capabilities. The capsule is bounded and its digest is
recorded by the host; do not put raw chat history, source, diffs or credentials in it.</p>

<h2>Hooks and SDK integration</h2>
<p>The MCP tools <code>yieldpoint_routing_profile</code>,
<code>yieldpoint_build_task_capsule</code> and <code>yieldpoint_handoff_check</code>
provide the same contracts for developers wiring an agent loop. The Python LangGraph
adapter supplies <code>make_admission_node</code> and <code>make_handoff_router</code>.
Node and Java validate the shared profile/session fixtures before their host routers act.
See the runnable <a href="%s/tree/main/examples">SDK and CLI examples</a>, including
the optional Jev adapter.</p>

<h2>Measure without collecting content</h2>
<pre><code>yieldpoint routing-stats</code></pre>
<p>This reads only the local <code>.yieldpoint/routing.jsonl</code> ledger. It contains
event counts, tier, selection source, switch counts, capsule size and handoff outcomes;
it never contains model names, prompts, provider payloads, diffs or secrets. Disable it
with <code>YIELDPOINT_NO_METRICS=1</code> or <code>"metrics": { "enabled": false }</code>.</p>
""" % REPO
