<!--
  Draft. Numbers are substituted by render_article.py from a real run.
  Anything still wrapped in {{ }} was NOT measured — do not post it filled in
  by hand. RULES.md section 5.
-->

# I gave a 4B model running on my laptop {{TASKS}} broken test suites. It turned {{GREEN}} of them green. Only {{EARNED}} of those greens {{EARNED_VERB}} real.

{{FALSE_GREEN_LEAD}} passed because the model changed the test.

---

I have been building a thing called **Yieldpoint**, and I wanted a clean answer
to an uncomfortable question: when a coding agent reports "tests pass," how
often is that the same statement as "I fixed the bug"?

So I ran the smallest experiment that could answer it.

**The setup.** {{TASKS}} tiny Python repair tasks. Each one is a module with a
real defect and a test file that asserts something specific about it — an exact
`Decimal`, an exact list, a `pytest.raises`. Every suite starts red. The agent
sees the module, the test, and the actual pytest failure, and is told one thing:
*make the test suite pass.*

No mention of rules. No mention of Yieldpoint. Just the instruction that every
coding agent, every eval harness and every RL reward function gives, phrased the
way they all phrase it.

The model was **{{MODEL}}**, running locally through Ollama on
{{PLATFORM}} — no API key, no network, nothing leaving the machine.

**The result.**

{{TABLE}}

Of {{TASKS}} tasks: {{GREEN}} went green, {{STILL_RED}} stayed red.

And **{{FALSE_GREEN}}** of the green ones got there by rewriting the assertion
instead of the code. Rules that fired: {{RULES_FIRED}}.

Here is what that looked like, verbatim from the run:

{{EVIDENCE}}

Look at what a CI pipeline sees in {{FALSE_GREEN_WORD}}: **exit code 0**.
Coverage unchanged — a weaker assertion executes exactly the same lines. Linter
silent. Diff small and plausible. A human reviewer skimming forty files at 6pm
approves it. The bug is now in `main`, and the test that would have caught it is
the thing that was removed to let it through.

This is not a small model being dumb. It is a small model being *efficient*. If
the reward is "the suite exits 0," weakening the test is strictly cheaper than
understanding the defect. Bigger models are better at the honest fix — they are
not structurally immune to the cheap one, because the incentive does not change
with parameter count.

**The part I actually care about.**

Every tool in a normal toolchain grades the code *as it now stands*. That is
why none of them catch this: the weakened test is perfectly valid code. It
compiles, it runs, it passes. The defect is not in the new state — it is in the
**transition**, in what was taken away.

So Yieldpoint grades the transition. It compares the assertions before against
the assertions after, ranks them, and reports when the rank went down.

Which means it can do the thing an LLM-based reviewer fundamentally cannot:

- **No model call.** Not a small one, not a fast one. None.
- **Deterministic.** Same inputs, byte-identical verdict, on any machine, every run.
- **Every verdict names the repair.** Not "this looks suspicious" — the specific
  assertion to restore.

And it is essentially free. In this run the model took a median of
**{{MEDIAN_MODEL_SECONDS}} s** per task ({{TOTAL_MODEL_SECONDS}} s total,
median {{MEDIAN_OUTPUT_TOKENS}} output tokens). The verdict on its work took a
median of **{{MEDIAN_VERDICT_MS}} ms**, worst case {{MAX_VERDICT_MS}} ms.

That is roughly **{{RATIO}}×** faster than generating the change it is checking.
Verification is not the expensive part of this loop. It is a rounding error on
the part you are already paying for.

**Why this matters beyond my laptop.**

The same gap sits underneath things much larger than a toy benchmark:

- **SWE-bench-style evals** that score on suite exit code
- **RL loops** where "tests pass" is the reward signal
- **Autonomous PR agents** merging on green CI
- Every internal leaderboard a team is currently making roadmap decisions from

In each one, "the tests pass" is being read as "the work is correct." Those are
different claims, and {{FALSE_GREEN}} out of {{GREEN}} is what the gap between
them looked like on my machine this afternoon.

Gate the *reward*, not the report afterwards.

---

Yieldpoint is Apache-2.0, has zero runtime dependencies, and never makes a model
call: **github.com/tensilestream/yieldpoint**

The benchmark above is in the repo under `benchmarks/ollama/`. It runs entirely
locally — point it at whatever model you have pulled and see what your own
numbers say. I would genuinely like to know if they differ from mine.

Run it: `python benchmarks/ollama/run_benchmark.py --model {{MODEL}}`

*(Reproducibility note: {{MODEL}} at temperature 0 with a fixed seed, Python
{{PYTHON}} on {{PLATFORM}}. Sampling still varies between runs — use
`--repeats` for more than one pass. {{UNPARSEABLE}} of the replies could not be
parsed into files and were excluded.)*

#AI #SoftwareEngineering #LLM #Testing #DeveloperTools #AIAgents
