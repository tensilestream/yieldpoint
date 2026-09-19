# Integration examples

Every example calls the same function. `verify_change(before, after, path, policy)`
returns a `Verdict`; everything below is a translation layer over that one call, which
is why adding a framework is a short file rather than a fork.

| File | Tech | Scenario |
|---|---|---|
| [`langgraph_repair_loop.py`](./langgraph_repair_loop.py) | LangGraph | Single agent: generate → verify → repair, with the prescription fed back |
| [`langgraph_fanout.py`](./langgraph_fanout.py) | LangGraph `Send` | **Many workers on one repo** — per-worker verdicts, pooled subjects, shared ledger |
| [`harness_middleware.py`](./harness_middleware.py) | Any agent loop | **Routing + gating** — pick the model by measured risk, refuse a bad edit before it runs |
| [`long_running_session.py`](./long_running_session.py) | Any | **Hours-long session** — incremental totals, budget guard, loop detection |
| [`crewai_guard.py`](./crewai_guard.py) | CrewAI | A verification step between task and commit |
| [`openai_agents_tool.py`](./openai_agents_tool.py) | OpenAI Agents SDK | Yieldpoint as a function tool |
| [`claude_agent_sdk_hook.py`](./claude_agent_sdk_hook.py) | Claude Agent SDK | `PreToolUse` gate — enforcement, not advice |
| [`plain_loop.py`](./plain_loop.py) | No framework | The whole pattern in 30 lines |
| [`eval_harness.py`](./eval_harness.py) | Any eval runner | **Anti-reward-hacking**: did the agent game the benchmark? |
| [`github_action.yml`](./github_action.yml) | GitHub Actions | Gate a pull request |
| [`gitlab_ci.yml`](./gitlab_ci.yml) | GitLab CI | The same, on a merge request |
| [`pytest_conftest.py`](./pytest_conftest.py) | pytest | Fail the suite if the suite itself was weakened |

## The one thing worth reading first

**A tool an agent calls is advice. A node it cannot route around is a gate.**

MCP tools and prompt rules depend on the agent choosing to ask, and an agent about to
weaken a test does not ask. Use them for *explanation* — they answer "why was that
rejected" deterministically and for free. Put enforcement where the agent has no vote: a
graph edge, a `PreToolUse` hook, pre-commit, or CI.

Both matter. They are not substitutes.

## Fan-out: the two things that actually bite

**Subjects move between workers.** Worker A relocates a test into a file worker B owns.
Each sees half the change, and each reports a loss that did not happen. Verify the
*combined* diff, or pass `also_covered` with the subjects found elsewhere — see
`langgraph_fanout.py`. Verifying per worker in isolation is the mistake.

**Attribution.** With three hundred workers, "the suite got weaker" is not actionable.
Set `YIELDPOINT_RUN_ID` and `YIELDPOINT_AGENT` per worker and `yieldpoint stats` reports
findings per agent, so the one worker with a bad prompt is visible.
