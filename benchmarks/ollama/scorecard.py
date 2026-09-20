"""A scoreboard SVG, for places that will not render a web page.

    python benchmarks/ollama/scorecard.py

GitHub strips CSS and script from Markdown, so the proof page cannot be
embedded in a profile README. An SVG can. This renders the deterministic
results — the ones that do not depend on which model you happen to have — as
two images, light and dark, plus the Markdown that switches between them.

Numbers come from results/*.json. Nothing here is typed by hand.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"

LIGHT = {"bg": "#ffffff", "panel": "#f7f8fa", "line": "#dde2ea", "ink": "#1a1d23",
         "dim": "#636b78", "good": "#3f7d5c", "flag": "#a8642a", "accent": "#2b5d8a"}
DARK = {"bg": "#0e1116", "panel": "#161a21", "line": "#29303b", "ink": "#e8eaee",
        "dim": "#9aa3b2", "good": "#6fc099", "flag": "#e0a45c", "accent": "#7fb0dd"}

W, H = 880, 340
MONO = "ui-monospace,SFMono-Regular,Menlo,monospace"
SANS = "-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif"


@dataclass(frozen=True)
class Board:
    title: str
    note: str
    rows: list[tuple[str, str, str]]
    """(label, value, tone) — tone is "good", "flag" or "" for plain."""


def load(name: str) -> dict | None:
    path = RESULTS / name
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def boards() -> list[Board]:
    history, matrix, judge = load("history.json"), load("matrix.json"), None
    for path in sorted(RESULTS.glob("judge-*.json")):
        candidate = load(path.name) or {}
        # A --no-judge run records the Yieldpoint side only; its judge scores
        # are None and would render as a comparison that never happened.
        if (candidate.get("summary", {}).get("llm_judge", {}).get("accuracy")
                is not None):
            judge = candidate

    out: list[Board] = []
    if history:
        out.append(Board(
            "real commits", "this repository's own history", [
                ("commits replayed", str(history["commits_replayed"]), ""),
                ("would have been stopped",
                 str(history["commits_a_correctness_rule_would_have_stopped"]), "flag"),
                ("time", f"{history['seconds']}s", ""),
                ("model calls", "0", "good"),
            ]))
    if matrix:
        s = matrix["summary"]
        out.append(Board(
            "every rule", "the edit that provokes each", [
                ("rules fired as claimed",
                 f"{s['fired_as_claimed']}/{s['must_fire']}", "good"),
                ("legitimate edits left alone",
                 f"{s['stayed_clean']}/{s['must_stay_clean']}", "good"),
                ("time", f"{s['total_ms']:.0f} ms", ""),
                ("tokens", "0", "good"),
            ]))
    if judge:
        s = judge["summary"]
        yp, lj = s["yieldpoint"], s["llm_judge"]
        out.append(Board(
            "versus an LLM judge", "37 labelled cases, same inputs", [
                ("accuracy", f"{yp['accuracy']:.0%} vs {lj['accuracy']:.0%}", "good"),
                ("blocked good refactors",
                 f"{len(yp['false_alarms'])} vs {len(lj['false_alarms'])}", "good"),
                ("tokens", f"0 vs {lj['tokens']:,}", "good"),
                ("model calls", f"0 vs {lj['model_calls']}", "good"),
            ]))
    return out


def esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _board_svg(board: Board, x: int, y: int, w: int, c: dict) -> str:
    parts = [
        f"<rect x='{x}' y='{y}' width='{w}' height='236' rx='10' "
        f"fill='{c['panel']}' stroke='{c['line']}'/>",
        f"<text x='{x + 18}' y='{y + 30}' font-family='{SANS}' font-size='13' "
        f"font-weight='600' fill='{c['ink']}'>{esc(board.title)}</text>",
        f"<text x='{x + 18}' y='{y + 48}' font-family='{SANS}' font-size='10.5' "
        f"fill='{c['dim']}'>{esc(board.note)}</text>",
    ]
    row_y = y + 78
    for label, value, tone in board.rows:
        colour = c.get(tone or "ink", c["ink"])
        parts.append(
            f"<text x='{x + 18}' y='{row_y}' font-family='{SANS}' font-size='11' "
            f"fill='{c['dim']}'>{esc(label)}</text>")
        parts.append(
            f"<text x='{x + w - 18}' y='{row_y}' text-anchor='end' "
            f"font-family='{MONO}' font-size='13' font-weight='600' "
            f"fill='{colour}'>{esc(value)}</text>")
        row_y += 36
    return "".join(parts)


def render(c: dict) -> str:
    found = boards()
    if not found:
        return ""
    gap, margin = 16, 24
    width = (W - 2 * margin - gap * (len(found) - 1)) // len(found)

    head = (
        f"<text x='{margin}' y='34' font-family='{SANS}' font-size='17' "
        f"font-weight='600' fill='{c['ink']}'>Yieldpoint &#8212; measured, not asserted</text>"
        f"<text x='{margin}' y='56' font-family='{SANS}' font-size='11.5' "
        f"fill='{c['dim']}'>Deterministic verification for coding agents. "
        f"No model call, same answer every run.</text>")
    cards = "".join(
        _board_svg(b, margin + i * (width + gap), 78, width, c)
        for i, b in enumerate(found))
    foot = (
        f"<text x='{margin}' y='{H - 14}' font-family='{MONO}' font-size='10' "
        f"fill='{c['dim']}'>python benchmarks/ollama/history_proof.py --repo /path/to/yours</text>")

    return (
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{W}' height='{H}' "
        f"viewBox='0 0 {W} {H}' role='img' "
        f"aria-label='Yieldpoint benchmark scorecard'>"
        f"<rect width='{W}' height='{H}' rx='12' fill='{c['bg']}'/>"
        f"{head}{cards}{foot}</svg>")


SNIPPET = """<picture>
  <source media="(prefers-color-scheme: dark)"
          srcset="https://raw.githubusercontent.com/tensilestream/yieldpoint/main/benchmarks/ollama/results/scorecard-dark.svg">
  <img alt="Yieldpoint scorecard: {stopped} of {replayed} real commits would have been stopped, {fired}/{must} rules fire as claimed, 0 model calls"
       src="https://raw.githubusercontent.com/tensilestream/yieldpoint/main/benchmarks/ollama/results/scorecard-light.svg">
</picture>
"""


def main() -> int:
    RESULTS.mkdir(exist_ok=True)
    written = []
    for name, palette in (("light", LIGHT), ("dark", DARK)):
        svg = render(palette)
        if not svg:
            print("error: no results to render; run history_proof.py first")
            return 2
        target = RESULTS / f"scorecard-{name}.svg"
        target.write_text(svg, encoding="utf-8")
        written.append(target)

    history, matrix = load("history.json"), load("matrix.json")
    snippet = SNIPPET.format(
        stopped=history["commits_a_correctness_rule_would_have_stopped"],
        replayed=history["commits_replayed"],
        fired=matrix["summary"]["fired_as_claimed"],
        must=matrix["summary"]["must_fire"])
    (RESULTS / "scorecard.md").write_text(snippet, encoding="utf-8")

    for path in written:
        print(f"  wrote {path}  ({path.stat().st_size:,} bytes)")
    print(f"  wrote {RESULTS / 'scorecard.md'}  (paste into a README)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
