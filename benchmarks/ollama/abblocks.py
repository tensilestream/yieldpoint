"""Page blocks for the measured runs: both A/Bs, the rule matrix, calibration.

Split out of htmlproof.py so both files stay inside the length limit this
project enforces on everyone else.
"""

from __future__ import annotations

import html

from htmlproof import rows, tag


def _outcome(r: dict) -> str:
    if r["tests_passed"] and r["tampering_rules"]:
        return tag("false green", "bad")
    return tag("earned", "good") if r["tests_passed"] else tag("still red")


def ab_block(data: dict) -> str:
    """The test-repair A/B: same task, same turn budget, gated and ungated."""
    s = data["summary"]
    a, b = s["without"], s["with"]
    head = ("<tr><th>task</th><th>ungated</th><th>turns</th>"
            "<th>gated</th><th>turns</th></tr>")
    body = "".join(
        f"<tr><th>{html.escape(p['without']['task'])}</th>"
        f"<td class='num'>{_outcome(p['without'])}</td>"
        f"<td class='num'>{p['without']['turns_used']}</td>"
        f"<td class='num'>{_outcome(p['with'])}</td>"
        f"<td class='num'>{p['with']['turns_used']}</td></tr>"
        for p in data["pairs"])
    return (
        "<p class='lead'>Test-repair tasks only &mdash; the narrower A/B. Same "
        "model, same seed, same turn budget; the gate is the single "
        "variable.</p>"
        f"<table class='rows'>{head}{body}</table>" +
        rows("", [
            ("earned greens",
             f"{a['earned']}/{a['tasks']} ungated &nbsp;&middot;&nbsp; "
             f"{b['earned']}/{b['tasks']} gated"),
            ("false greens",
             f"{a['false_green']} &nbsp;&middot;&nbsp; {b['false_green']}"),
            ("model tokens",
             f"{a['total_tokens']:,} &nbsp;&middot;&nbsp; {b['total_tokens']:,} "
             f"({s['delta']['extra_tokens']:+,})"),
            ("tokens spent verifying", "0 &nbsp;&middot;&nbsp; 0"),
        ]))


def calibration_block(data: dict) -> str:
    """Whether CHARS_PER_TOKEN = 4 survives contact with a real tokenizer."""
    cal = data["summary"].get("calibration") or {}
    out, inp = cal.get("output") or {}, cal.get("prompt") or {}
    if not out.get("samples"):
        return ""
    return rows("", [
        ("assumed, in ledger.CHARS_PER_TOKEN", out["assumed_chars_per_token"]),
        ("measured on generated text",
         f"{out['measured_chars_per_token']} chars/token"),
        ("measured on prompt text",
         f"{inp.get('measured_chars_per_token', '&mdash;')} chars/token"),
        ("error in a characters/4 estimate", f"{out['estimate_error']:+.0%}"),
    ]) + f"<p class='lead'>{html.escape(out['reading'])}</p>"


def _rule_cell(arm: dict) -> str:
    if arm["clean"]:
        return tag("clean", "good")
    return " ".join(tag(r, "bad") for r in arm["rules"]) or tag(arm["status"])


def _rule_row(pair: dict) -> str:
    w, v = pair["without"], pair["with"]
    return (f"<tr><th>{html.escape(w['task'])}"
            f"<p class='fix'>{html.escape(w['family'])}</p></th>"
            f"<td class='num'>{_rule_cell(w)}</td>"
            f"<td class='num'>{_rule_cell(v)}</td>"
            f"<td class='num'>{w['turns_used']} &rarr; {v['turns_used']}</td></tr>")


def _not_provoked(missed: list) -> str:
    """Rows where the request did not provoke its rule. Reported, not dropped."""
    if not missed:
        return ""
    return ("<p class='lead'>Requests that did not provoke the rule they were "
            f"written for: <code>{html.escape(', '.join(missed))}</code>. The "
            "model wrote acceptable code unprompted, so those rows compare "
            "nothing. Reported rather than dropped &mdash; a task list quietly "
            "pruned to the ones that worked is not a measurement.</p>")


def rule_ab_block(data: dict) -> str:
    """The broad A/B: every rule family, the same request gated and ungated."""
    s = data["summary"]
    a, b = s["without"], s["with"]
    head = ("<tr><th>the request</th><th>ungated result</th>"
            "<th>gated result</th><th>turns</th></tr>")
    body = "".join(_rule_row(pair) for pair in data["pairs"])
    caveat = _not_provoked(s["targets_not_provoked"])

    return (
        "<p class='lead'>Ten ordinary requests &mdash; add a helper module, add a "
        "dispatcher, rename a function, make CI green, fix a failing test &mdash; "
        "each answered twice by the same local model with the same turn budget "
        "and seed. The only difference is whether the verdict was fed back.</p>"
        f"<table class='rows'>{head}{body}</table>" +
        rows("", [
            ("output with no findings",
             f"<b>{a['clean']}/{a['tasks']}</b> ungated &nbsp;&middot;&nbsp; "
             f"<b>{b['clean']}/{b['tasks']}</b> gated"),
            ("repaired once told", ", ".join(s["repaired"]) or "none"),
            ("still failing at the turn limit", ", ".join(s["unrepaired"]) or "none"),
            ("turns", f"{a['turns']} &nbsp;&middot;&nbsp; {b['turns']}"),
            ("model tokens",
             f"{a['tokens']:,} &nbsp;&middot;&nbsp; {b['tokens']:,} "
             f"({s['delta']['extra_tokens']:+,})"),
            ("tokens spent verifying", "0 &nbsp;&middot;&nbsp; 0"),
            ("time spent verifying",
             f"{a['verdict_ms']:.0f} ms &nbsp;&middot;&nbsp; {b['verdict_ms']:.0f} ms"),
        ]) + caveat)


def matrix_block(m: dict) -> str:
    """Every rule, as the agent action that provokes it, grouped by that action."""
    s = m["summary"]
    head = ("<tr><th>what the agent did</th><th>rule</th>"
            "<th>verdict</th></tr>")
    body, action = [], None
    for r in m["results"]:
        if r["action"] != action:
            action = r["action"]
            body.append(f"<tr><th colspan='3'><b>{html.escape(action)}</b></th></tr>")
        clean = not r["expect"]
        rule = tag("stays clean", "good") if clean else tag(r["expect"], "bad")
        got = (tag("clean", "good") if clean and not r["rules"]
               else tag(r["status"], "bad") if r["rules"] else tag(r["status"]))
        body.append(
            f"<tr><th>{html.escape(r['name'])}"
            f"<p class='fix'>{html.escape(r['intent'])} &mdash; "
            f"<code>{html.escape(r['path'])}</code></p></th>"
            f"<td class='num'>{rule}</td><td class='num'>{got}</td></tr>")
    note = (
        f"<p class='lead'><b>{s['fired_as_claimed']} of {s['must_fire']}</b> rules "
        f"fired on the edit that provokes them, and <b>{s['stayed_clean']} of "
        f"{s['must_stay_clean']}</b> legitimate edits came back clean &mdash; "
        f"{len(s['distinct_rules'])} distinct rules in {s['total_ms']:.0f} ms, with "
        f"{s['model_calls']} model calls and {s['tokens']} tokens. The clean rows "
        "matter as much as the others: a checker that fires on real work is one "
        "people turn off.</p>")
    return f"<table class='rows'>{head}{''.join(body)}</table>{note}"


def headline_block(data: dict) -> str:
    """The three numbers that decide whether this is worth installing.

    Accuracy, tokens, turns — and the ratio between them, because the raw token
    count on its own reads as a straight loss and the raw accuracy on its own
    reads as a free win. Neither is true alone.
    """
    s = data["summary"]
    a, b = s["without"], s["with"]
    per_a = a["tokens"] // a["clean"] if a["clean"] else None
    per_b = b["tokens"] // b["clean"] if b["clean"] else None

    def row(label: str, left, right, note: str = "") -> str:
        extra = f"<p class='fix'>{note}</p>" if note else ""
        return (f"<tr><th>{label}{extra}</th>"
                f"<td class='num'>{left}</td><td class='num'>{right}</td></tr>")

    body = (
        row("code with no problems",
            f"<b>{a['clean']}/{a['tasks']}</b>", f"<b>{b['clean']}/{b['tasks']}</b>",
            "the point of the whole thing") +
        row("tokens spent", f"{a['tokens']:,}", f"{b['tokens']:,}",
            "more, because bad work gets redone") +
        row("turns taken", a["turns"], b["turns"]) +
        row("tokens per good answer",
            f"{per_a:,}" if per_a else "&mdash;",
            f"{per_b:,}" if per_b else "&mdash;",
            "the honest comparison") +
        row("cost of the check itself", "&mdash;",
            f"0 tokens, {b['verdict_ms']:.0f} ms",
            "no model call, ever"))

    return (
        "<table class='rows'><tr><th></th><th>without Yieldpoint</th>"
        f"<th>with Yieldpoint</th></tr>{body}</table>"
        "<p class='lead'>You pay about the same per answer you can trust, and "
        "you get more of them. It is not a way to spend less &mdash; the check "
        "is free, fixing what it finds is not.</p>")


def history_block(data: dict) -> str:
    """Real commits from a real repository. No model, no fixtures."""
    rows_ = rows("", [
        ("commits replayed", f"{data['commits_replayed']}"),
        ("commits a correctness rule would have stopped",
         f"<b>{data['commits_a_correctness_rule_would_have_stopped']}</b>"),
        ("time taken", f"{data['seconds']}s"),
        ("model calls", f"{data['model_calls']}"),
        ("tokens", f"{data['tokens']}"),
    ])

    commits = []
    for commit in data["stopped"]:
        items = []
        for f in commit["findings"]:
            removed = (f"<pre class='code'>{html.escape(f['before'])}</pre>"
                       if f["before"] else "")
            items.append(
                f"<li><span class='rule'>{html.escape(f['rule'])}</span> "
                f"{html.escape(f['file'])}:{f['line']}{removed}</li>")
        commits.append(
            f"<h3><code>{html.escape(commit['sha'])}</code> "
            f"{html.escape(commit['subject'][:60])}</h3>"
            f"<ul class='findings'>{''.join(items)}</ul>")

    return (
        "<p class='lead'>Every commit in this repository, re-verified as the "
        "change it was when it was made. These are assertions that were "
        "silently deleted from real tests, by real people, and merged.</p>"
        + rows_ + "".join(commits) +
        "<p class='lead'>Yieldpoint cannot tell you which of these were "
        "wrong &mdash; that judgement is the point of running it on your own "
        "history rather than on a demo. Run "
        "<code>python benchmarks/ollama/history_proof.py --repo /path/to/yours</code> "
        "and read what it finds.</p>")
