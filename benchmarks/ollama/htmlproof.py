"""Render the walkthrough as a page a human can read in two minutes.

    python benchmarks/ollama/htmlproof.py

Leads with the code and what happened to it. The measured numbers come after,
because a number nobody can picture is not evidence. Everything on the page was
produced by running ``walkthrough.py``; the benchmark JSONs, when present, add
the measured cost comparison.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pagetext import EXTRA_CSS, REPRODUCE, SETUP  # noqa: E402
from yieldpoint.pageshell import document  # noqa: E402

RESULTS = Path(__file__).resolve().parent / "results"

def code(text: str, *, diff: bool = False) -> str:
    if not diff:
        return f"<pre class='code'>{html.escape(text.rstrip())}</pre>"
    out = []
    for line in text.rstrip().splitlines():
        cls = ("hunk" if line.startswith(("@@", "---", "+++"))
               else "add" if line.startswith("+")
               else "del" if line.startswith("-") else "")
        safe = html.escape(line)
        out.append(f"<span class='{cls}'>{safe}</span>" if cls else safe)
    return "<pre class='code'>" + "\n".join(out) + "</pre>"


def tag(text: str, kind: str = "") -> str:
    suffix = f" is-{kind}" if kind else ""
    return f"<span class='tag{suffix}'>{html.escape(text)}</span>"


def section(name: str, note: str, body: str) -> str:
    tier = f"tier-{name.split()[0].lower()}"
    return (f"<section class='{tier}'><div class='tier-head'>"
            f"<h2>{html.escape(name)}</h2>"
            f"<span class='note'>{html.escape(note)}</span></div>{body}</section>")


def rows(title: str, pairs) -> str:
    head = f"<h3>{html.escape(title)}</h3>" if title else ""
    body = "".join(f"<tr><th>{a}</th><td class='num'>{b}</td></tr>" for a, b in pairs)
    return f"{head}<table class='rows'>{body}</table>"


def scenario_block(s: dict) -> str:
    return (
        "<p class='lead'>A volume-discount bug. The tiers are documented as "
        "inclusive &mdash; spend 500 or more, get 10% &mdash; but the comparison "
        "is strict, so an order landing exactly on a boundary is quietly "
        "undercharged. One test catches it, and that test is red.</p>"
        "<div class='two'>"
        f"<div><h3>{html.escape(s['source_path'])} &mdash; the bug</h3>"
        f"{code(s['source'])}</div>"
        f"<div><h3>{html.escape(s['test_path'])} &mdash; the test that catches it</h3>"
        f"{code(s['test'])}</div></div>"
        f"<h3>The starting state</h3>{code(s['pytest_tail'])}"
        "<p class='lead'>Now an agent is told the only thing agents are ever "
        "told: <b>make the tests pass</b>.</p>"
    )


def shortcut_table(story: dict) -> str:
    head = ("<tr><th>what the agent did</th><th>pytest</th>"
            "<th>Yieldpoint</th><th>bug still there?</th></tr>")
    body = []
    for a in story["shortcuts"] + [story["honest"]]:
        honest = a is story["honest"]
        suite = tag("green" if a["tests_pass"] else "red",
                    "good" if a["tests_pass"] else "bad")
        verdict = (tag(a["status"], "bad") if a["caught"]
                   else tag(a["status"], "good" if honest else ""))
        still = tag("fixed", "good") if honest else tag("yes", "bad")
        body.append(
            f"<tr><th>{html.escape(a['name'])}"
            f"<p class='fix'>{html.escape(a['intent'])}</p></th>"
            f"<td class='num'>{suite}</td><td class='num'>{verdict}</td>"
            f"<td class='num'>{still}</td></tr>")
    t = story["totals"]
    note = (f"<p class='lead'>{t['shortcuts_that_turn_the_suite_green']} of "
            f"{t['shortcuts_tried']} shortcuts turn the suite green. "
            f"<b>pytest cannot tell any of them from the real fix.</b> "
            f"Yieldpoint catches {t['caught_by_yieldpoint']} of them, in "
            f"{t['verdict_ms_total']:.0f} ms, with {t['model_calls']} model "
            f"calls.</p>")
    return f"<table class='rows'>{head}{''.join(body)}</table>{note}"


def caught_example(story: dict) -> str:
    """One catch, in full: the edit, and the exact words that come back."""
    a = next((x for x in story["shortcuts"] if x["caught"]), None)
    if not a:
        return ""
    return (
        f"<h3>The edit</h3>{code(a['diff'], diff=True)}"
        f"<h3>pytest</h3>{code(a['pytest_tail'])}"
        "<p class='lead'>Green. Coverage unchanged &mdash; a weaker assertion "
        "runs the same lines. A reviewer skimming forty files approves it.</p>"
        f"<h3>Yieldpoint, on the same edit</h3>"
        f"<div class='verdict'>{code(a['prescription'])}</div>"
        f"<p class='lead'>Status <b>{html.escape(a['status'])}</b>, in "
        f"{a['verdict_ms']:.1f} ms. The prescription names the assertion to put "
        f"back &mdash; it is assembled from the parse, not written by a model, "
        f"so it costs nothing and reads the same on every machine.</p>")


def honest_limits(story: dict) -> str:
    missed = [a for a in story["shortcuts"] if a["tests_pass"] and not a["caught"]]
    if not missed:
        return "<p class='lead'>Every shortcut in this example was caught.</p>"
    a = missed[0]
    return (
        f"<p class='lead'>One of the five gets through: <b>{html.escape(a['name'])}"
        f"</b> &mdash; {html.escape(a['intent'])}.</p>"
        f"{code(a['diff'], diff=True)}"
        f"<p class='lead'>Yieldpoint returns <b>{html.escape(a['status'])}</b>. "
        "The assertion is still an exact equality, so it is exactly as strong as "
        "it was; only the expected value moved. That is indistinguishable from a "
        "legitimate correction to a spec, and a rule that flagged it would fire "
        "on every genuine change to an expected value. This tool measures "
        "assertion <i>strength</i>, not whether a constant is right. "
        "Knowing what a check does not cover is the difference between a gate "
        "and a comfort blanket.</p>")


def cost_block(story: dict, ab: dict | None, judge: dict | None) -> str:
    """Where the tokens actually go. Authoring is unchanged; only review moves."""
    t = story["totals"]
    author = "not measured here"
    if ab:
        a, b = ab["summary"]["without"], ab["summary"]["with"]
        author = (f"{a['total_tokens']:,} without, {b['total_tokens']:,} with "
                  f"&mdash; a difference of {ab['summary']['delta']['extra_tokens']:+,}")
    per_verdict = (f"{judge['summary']['llm_judge']['median_tokens_per_verdict']:,}"
                   if judge else "~226")

    ledger = rows("", [
        ("<b>1. the agent writes the code</b>"
         "<p class='fix'>happens either way; Yieldpoint changes nothing here</p>",
         author),
        ("<b>2. checking whether the change weakened the tests</b>"
         "<p class='fix'>this is the only line Yieldpoint moves</p>",
         f"{per_verdict} tokens + 1 model call per verdict with an LLM judge, "
         f"<b>0 and 0</b> with Yieldpoint"),
        ("<b>3. repairing a change it rejected</b>"
         "<p class='fix'>only when it actually fires</p>",
         "one extra turn, at normal agent rates"),
    ])
    return (
        "<p class='lead'>A fair answer has to separate three different costs, "
        "because only one of them changes.</p>" + ledger +
        "<h3>So does it save tokens? It depends what it replaces.</h3>"
        "<table class='rows'>"
        "<tr><th>If today you check with an <b>LLM reviewer</b>"
        "<p class='fix'>a judge model, a review agent, a self-critique step</p></th>"
        f"<td class='num'>you save {per_verdict} tokens and 1 call "
        f"<b>per change reviewed</b></td></tr>"
        "<tr><th>If today you check with <b>nothing</b>"
        "<p class='fix'>the common case: green CI is the gate</p></th>"
        "<td class='num'>you save no tokens. You gain a check that "
        "costs none</td></tr>"
        "<tr><th>If the check <b>fires</b>"
        "<p class='fix'>a weakened test was actually caught</p></th>"
        "<td class='num'>you spend <b>more</b>: a repair turn you would "
        "not otherwise have paid for</td></tr>"
        "</table>"
        "<p class='lead'>It is not a way to spend less on your agent. It is a "
        "review step whose own cost is zero &mdash; "
        f"{t['verdict_ms_total']:.0f} ms and {t['tokens']} tokens for all "
        f"{t['shortcuts_tried']} checks on this page &mdash; and which is "
        "deterministic, so the same change gets the same answer every time.</p>")


def measured_block(judge: dict) -> str:
    s = judge["summary"]
    yp, lj = s["yieldpoint"], s["llm_judge"]
    return (
        "<p class='lead'>The alternative to a deterministic check is asking a "
        "model. Both were run over the same 37 labelled cases from this "
        "repository's corpus &mdash; 18 real weakenings, 19 legitimate "
        "refactors &mdash; and scored against the labels, not against each "
        "other.</p>" +
        rows("", [
            ("accuracy",
             f"<b>{yp['accuracy']:.0%}</b> Yieldpoint &nbsp;&middot;&nbsp; "
             f"{lj['accuracy']:.0%} LLM judge"),
            ("missed a real weakening",
             f"{len(yp['missed_tampering'])} &nbsp;&middot;&nbsp; "
             f"{len(lj['missed_tampering'])}"),
            ("blocked legitimate refactors",
             f"{len(yp['false_alarms'])} &nbsp;&middot;&nbsp; "
             f"<b>{len(lj['false_alarms'])}</b> of 19"),
            ("model calls", f"0 &nbsp;&middot;&nbsp; {lj['model_calls']}"),
            ("tokens", f"0 &nbsp;&middot;&nbsp; {lj['tokens']:,}"),
            ("wall clock",
             f"{yp['total_ms']:.0f} ms &nbsp;&middot;&nbsp; "
             f"{lj['total_seconds']:.0f} s"),
        ]) +
        f"<p class='lead'>The judge blocked {len(lj['false_alarms'])} of 19 "
        "legitimate refactors &mdash; including one that <i>strengthened</i> a "
        "test by adding a match pattern. Being non-deterministic, it would "
        "block a different set on the next run.</p>")


@dataclass(frozen=True)
class Results:
    """Whatever result files exist. Each section renders only if its data does."""

    story: dict
    ab: dict | None = None
    judge: dict | None = None
    matrix: dict | None = None
    rule_ab: dict | None = None
    history: dict | None = None


def _evidence(r: Results) -> list[str]:
    """The sections that need no model, first: they are the load-bearing ones."""
    from abblocks import headline_block, history_block, matrix_block, rule_ab_block

    parts = []
    if r.history:
        parts.append(section("Caught on real commits",
                             "this repository's own history, no model",
                             history_block(r.history)))
    if r.rule_ab:
        parts.append(section("In one table", "measured on this machine",
                             headline_block(r.rule_ab)))
    parts += [
        section("The code", "benchmarks/ollama/example_repo, runnable",
                scenario_block(r.story["scenario"])),
        section("Five ways to make it green", "all of them pass; one is honest",
                shortcut_table(r.story)),
        section("One of them, in full", "the edit, and what comes back",
                caught_example(r.story)),
        section("What it does not catch", "stated, not omitted",
                honest_limits(r.story)),
    ]
    if r.rule_ab:
        parts.append(section("The same request, gated and ungated",
                             "every rule family, identical turn budget",
                             rule_ab_block(r.rule_ab)))
    if r.matrix:
        parts.append(section("Every rule, and the edit that provokes it",
                             "new files, new methods, rewrites, tests, CI",
                             matrix_block(r.matrix)))
    return parts


def build(r: Results) -> str:
    from abblocks import ab_block, calibration_block

    policy = (Path(__file__).resolve().parent
              / "example_repo" / ".yieldpoint.json").read_text().strip()
    parts = [EXTRA_CSS] + _evidence(r)
    parts.append(section("What it costs", "authoring, checking, repairing",
                         cost_block(r.story, r.ab, r.judge)))
    if r.ab:
        parts.append(section("The narrower A/B: test repair only",
                             "eight repair tasks, same budget both arms",
                             ab_block(r.ab)))
        cal = calibration_block(r.ab)
        if cal:
            parts.append(section("Calibration",
                                 "the one constant the estimates rest on", cal))
    if r.judge:
        parts.append(section("Measured against a real LLM judge",
                             "37 labelled cases, same inputs, gemma4 locally",
                             measured_block(r.judge)))
    parts.append(section("Adding it", "three steps",
                         SETUP.format(policy=html.escape(policy))))
    parts.append(section("Reproduce this page", "it is all scripts", REPRODUCE))
    return "".join(parts)


def load(name: str) -> dict | None:
    found = sorted(RESULTS.glob(name), key=lambda p: p.stat().st_mtime)
    if not found:
        return None
    try:
        return json.loads(found[-1].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def regenerate(out: Path | None = None) -> Path | None:
    """Rebuild the page from whatever results exist. Never raises."""
    story = load("story.json")
    if story is None:
        return None
    try:
        target = out or (RESULTS / "proof.html")
        target.write_text(document(
            title="Yieldpoint — what it catches, and what it costs",
            heading="Your agent made the tests pass. Did it fix the bug?",
            scope="every figure produced by running the scripts at the foot of "
                  "this page, on this machine",
            source="benchmarks/ollama/example_repo",
            body=build(Results(
                story, load("ab-*.json"), load("judge-*.json"),
                load("matrix.json"), load("ruleab-*.json"),
                load("history.json"))),
        ), encoding="utf-8")
        return target
    except (OSError, ValueError, KeyError) as exc:
        print(f"note: could not write the page: {exc}", file=sys.stderr)
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    page = regenerate(Path(args.out) if args.out else None)
    if page is None:
        print("error: no results/story.json. Run walkthrough.py first.",
              file=sys.stderr)
        return 2
    print(f"wrote {page}  ({page.stat().st_size:,} bytes, self-contained)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
