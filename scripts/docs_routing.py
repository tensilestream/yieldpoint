"""Provider-neutral routing page kept separate from the established docs pages."""

REPO = "https://github.com/tensilestream/yieldpoint"




def routing_page() -> str:
    """Assemble the page from its sections, so each stays readable on its own."""
    return "\n".join((
        _intro(),
        _observe_only(),
        _bounds(),
        _lifecycle(),
        _evidence(),
        _integration(),
        _measure(),
    ))


def _intro() -> str:
    return """<h1>Safe model routing</h1>
<p class="lede">Yieldpoint can describe what a change needs without selecting a model or
calling a provider. Your host owns models, keys, vendor requests and final actions.</p>"""


def _observe_only() -> str:
    return """<h2>Start observe-only</h2>
<pre><code>{
  "routing_session": {
    "enabled": true,
    "max_model_switches": 1,
    "capsule_max_chars": 12000,
    "router_overhead_fraction": 0.05,
    "allow_unverified": false,
    "checkpoint_events": ["verification_failed", "repair_exhausted", "loop_tripped"]
  }
}</code></pre>
<p>Routing is off by default, and off means off: with <code>enabled</code> false,
<code>assess</code> returns exactly what it returned before routing existed. Turn it on
first in a non-enforcing integration, compare the recommended tier with the model that
actually completed the task, then choose any provider policy outside Yieldpoint. Do not
use an uncalibrated confidence value as permission to act.</p>"""


def _bounds() -> str:
    return """<h2>Every bound travels with the profile</h2>
<p>The profile&rsquo;s <code>handoff</code> block carries the switch budget, the live
checkpoint events, the overhead ceiling and the unverified policy. That is deliberate:
the Node and Java hosts receive only this document, so a limit left behind in Python
would be a limit they could not apply. The block is covered by the profile&rsquo;s
<code>profile_id</code> digest, which the Python engine recomputes whenever it reads a
profile back &mdash; so a profile edited to widen its own budget is refused by the CLI
and the MCP tools rather than honoured. Node and Java validate structure and pairing
and apply the bounds; the digest stays the canonical engine&rsquo;s to check.</p>"""


def _lifecycle() -> str:
    return """<h2>One admission, one bounded handoff</h2>
<pre><code>git diff &gt; change.diff
yieldpoint assess-routing --diff change.diff --verdict verdict.json --repair-attempt 1
yieldpoint build-capsule --profile profile.json --session session.json \\
  --objective "Charge each line item at its own price" --acceptance "Unit tests pass"
yieldpoint handoff-check --profile profile.json --session session.json \\
  --event verification_failed --overhead 0.04 \\
  --capability strong_reasoning --capability tool_use</code></pre>
<p><code>--diff</code> profiles the whole change set, which is usually what a task is:
the riskiest file decides the tier, every file&rsquo;s requirements accumulate, and one
file the engine cannot read makes the whole set inexact. Use
<code>--path</code>/<code>--after</code> for a single file.</p>
<p>Keep the admitted model for normal work. A handoff is allowed only at a checkpoint
your policy lists, only within the switch budget, only when the estimated router and
capsule input fits <code>router_overhead_fraction</code>, and only when the candidate
has every capability the profile requires. Each refusal names the bound it failed.</p>"""


def _evidence() -> str:
    return """<h2>Route on evidence, not on its absence</h2>
<p>Pass <code>--verdict</code>. Without one the profile reports
<code>unverified</code>, and an unverified change is not handed to a larger model:
there is no evidence a stronger model would help, and spending one to find out is the
cost this feature exists to avoid. A <code>pass</code> buys no second opinion and a
<code>block</code> is a person&rsquo;s decision; neither is routed around. Set
<code>allow_unverified</code> if your pipeline genuinely wants the opposite.</p>"""


def _integration() -> str:
    return """<h2>Hooks and SDK integration</h2>
<p>The MCP tools <code>yieldpoint_routing_profile</code>,
<code>yieldpoint_build_task_capsule</code> and <code>yieldpoint_handoff_check</code>
provide the same contracts for developers wiring an agent loop. The Python LangGraph
adapter supplies <code>make_admission_node</code> and <code>make_handoff_router</code>;
admission reads the verdict, repair count and loop state already in graph state, so
placing it after a verify node is all the wiring it needs. Node and Java apply the same
bounds from the same profile, checked against shared fixtures.
See the runnable <a href="%s/tree/main/examples">SDK and CLI examples</a>, including
the optional Jev adapter.</p>""" % REPO


def _measure() -> str:
    return """<h2>Measure without collecting content</h2>
<pre><code>yieldpoint routing-stats</code></pre>
<p>This reads only the local <code>.yieldpoint/routing.jsonl</code> ledger. It contains
event counts, tier, selection source, switch counts, capsule size and handoff outcomes;
it never contains model names, prompts, provider payloads, diffs or secrets. Disable it
with <code>YIELDPOINT_NO_METRICS=1</code> or <code>"metrics": { "enabled": false }</code>.</p>"""
