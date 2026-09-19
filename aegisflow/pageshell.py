"""The page shell: stylesheet, masthead, and the slots the report fills.

Separated from htmlreport.py because the two change for different reasons —
that file changes when there is a new thing worth reporting, this one when
there is a better way to look at it. It also keeps both under the length limit
this project enforces on everyone else.

Three theme states are handled, not two: an explicit choice stamps the root
element, and the default "system" setting stamps nothing at all. Every colour
is a token defined in the bare ``:root``, so the un-stamped state resolves a
complete palette rather than half of one.
"""

from __future__ import annotations

import html

_TEMPLATE = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>
  /* Light is the base set. Every colour is a token so both themes resolve
     together; nothing is defined only inside a media query. */
  :root {
    --ground:  #f7f8fa;
    --panel:   #ffffff;
    --sunk:    #eef1f5;
    --line:    #dde2ea;
    --ink:     #1a1d23;
    --dim:     #636b78;
    --faint:   #8d95a3;
    --accent:  #2b5d8a;
    --signal:  #a8642a;
    --clean:   #3f7d5c;
    --shadow:  0 1px 2px rgba(20, 28, 42, .06), 0 8px 24px rgba(20, 28, 42, .05);
    --sans: "IBM Plex Sans", ui-sans-serif, -apple-system, "Segoe UI", sans-serif;
    --mono: "IBM Plex Mono", ui-monospace, "SF Mono", Menlo, monospace;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --ground: #0e1116; --panel: #161a21; --sunk: #1c212a; --line: #29303b;
      --ink: #e8eaee; --dim: #9aa3b2; --faint: #79828f;
      --accent: #7fb0dd; --signal: #e0a45c; --clean: #6fc099;
      --shadow: 0 1px 2px rgba(0, 0, 0, .4), 0 8px 24px rgba(0, 0, 0, .3);
    }
  }
  :root[data-theme="dark"] {
    --ground: #0e1116; --panel: #161a21; --sunk: #1c212a; --line: #29303b;
    --ink: #e8eaee; --dim: #9aa3b2; --faint: #79828f;
    --accent: #7fb0dd; --signal: #e0a45c; --clean: #6fc099;
    --shadow: 0 1px 2px rgba(0, 0, 0, .4), 0 8px 24px rgba(0, 0, 0, .3);
  }

  * { box-sizing: border-box; }
  body {
    margin: 0;
    padding: 2rem 1.5rem 3rem;
    background: var(--ground);
    color: var(--ink);
    font: 400 15px/1.65 var(--sans);
    -webkit-font-smoothing: antialiased;
  }
  main { max-width: 100rem; margin: 0 auto; display: flex;
         flex-direction: column; gap: 1.5rem; }

  /* Two columns on a real screen: what to do on the left, where it stays in
     view, and the accounting beside it rather than a screen below it. */
  .split { display: grid; gap: 1.5rem 2rem; align-items: start;
           grid-template-columns: minmax(0, 3fr) minmax(0, 2fr); }
  @media (max-width: 68rem) { .split { grid-template-columns: minmax(0, 1fr); } }
  .split > .col { display: flex; flex-direction: column; gap: 1.75rem;
                  min-width: 0; }

  .verdict { display: flex; flex-direction: column; gap: .2rem;
             padding: .9rem 1.1rem; border-radius: 6px; border: 1px solid;
             border-left-width: 4px; background: var(--panel); }
  .verdict b { font-size: 1.05rem; font-weight: 600; }
  .verdict span { font-size: .875rem; color: var(--dim); }
  .verdict.is-blocking { border-color: var(--signal); }
  .verdict.is-blocking b { color: var(--signal); }
  .verdict.is-clean { border-color: var(--clean); }
  .verdict.is-clean b { color: var(--clean); }
  .verdict.is-advisory, .verdict.is-quiet { border-color: var(--line); }

  .pace { background: var(--panel); border: 1px solid var(--line);
          border-radius: 6px; padding: .8rem 1.1rem;
          display: flex; flex-direction: column; gap: .45rem; }
  .pace-top { display: flex; justify-content: space-between;
              align-items: baseline; gap: 1rem; flex-wrap: wrap; }
  .pace b { font: 500 .72rem/1 var(--mono); letter-spacing: .14em;
            text-transform: uppercase; }
  .pace .num { font-size: .8rem; color: var(--dim); }
  .pace p { margin: 0; font-size: .875rem; color: var(--dim); }
  .gauge { display: block; height: .45rem; border-radius: 2px;
           background: var(--sunk); overflow: hidden; }
  .gauge > span { display: block; height: 100%; background: var(--accent); }
  .pace.is-warn b { color: var(--signal); }
  .pace.is-warn .gauge > span { background: var(--signal); }
  .pace.is-over { border-color: var(--signal); }
  .pace.is-over b { color: var(--signal); }
  .pace.is-over .gauge > span { background: var(--signal); }

  .findings { list-style: none; margin: 0; padding: 0;
              display: flex; flex-direction: column; gap: .6rem; }
  .findings li { background: var(--panel); border: 1px solid var(--line);
                 border-left: 3px solid var(--line); border-radius: 5px;
                 padding: .7rem .9rem; display: flex;
                 flex-direction: column; gap: .3rem; }
  .findings li.is-blocking { border-left-color: var(--signal); }
  .where { display: flex; gap: .6rem; align-items: baseline;
           flex-wrap: wrap; }
  .where code { font-size: .8rem; }
  .rule { font: 500 .65rem/1 var(--mono); letter-spacing: .09em;
          text-transform: uppercase; color: var(--dim); }
  .findings li.is-blocking .rule { color: var(--signal); }
  .what { margin: 0; font-size: .9rem; }
  .fix { margin: 0; font-size: .85rem; color: var(--dim); }
  .more { font-size: .85rem; color: var(--dim); margin: .25rem 0 0; }

  .masthead { display: flex; flex-direction: column; gap: .4rem; }
  .eyebrow {
    font: 500 .7rem/1 var(--mono); letter-spacing: .14em;
    text-transform: uppercase; color: var(--accent);
  }
  h1 { font-size: 1.75rem; font-weight: 600; letter-spacing: -.015em;
       margin: 0; text-wrap: balance; }
  .scope { color: var(--dim); font: 400 .875rem/1.5 var(--mono); margin: 0; }

  .cards { display: grid; gap: .75rem;
           grid-template-columns: repeat(auto-fit, minmax(9.5rem, 1fr)); }
  .card {
    background: var(--panel); border: 1px solid var(--line);
    border-radius: 6px; padding: 1rem 1.1rem; box-shadow: var(--shadow);
    display: flex; flex-direction: column; gap: .15rem;
  }
  .card .value {
    font: 600 1.6rem/1.1 var(--sans); letter-spacing: -.03em;
    font-variant-numeric: tabular-nums;
  }
  .card .label { font: 500 .7rem/1.4 var(--mono); letter-spacing: .1em;
                 text-transform: uppercase; color: var(--dim); }
  .card .note { font-size: .78rem; color: var(--faint); margin-top: .3rem; }
  .card.is-zero .value { color: var(--clean); }

  /* The three tiers of claim differ in visual weight, because they differ in
     how much they can be trusted. Solid, ruled, then dashed and recessed. */
  section { display: flex; flex-direction: column; gap: .5rem; }
  .tier-head { display: flex; align-items: baseline; gap: .75rem;
               flex-wrap: wrap; padding-bottom: .5rem;
               border-bottom: 1px solid var(--line); }
  h2 { font: 500 .72rem/1 var(--mono); letter-spacing: .16em;
       text-transform: uppercase; margin: 0; color: var(--ink); }
  .tier-head .note { font-size: .8rem; color: var(--dim); }
  .tier-estimated .tier-head { border-bottom-style: dashed; }
  .tier-estimated h2 { color: var(--dim); }
  .tier-estimated .rows { opacity: .88; }
  .tier-estimated .rows tr:nth-child(odd) { background: transparent; }
  .tier-estimated .rows th, .tier-estimated .rows td {
    border-bottom: 1px dashed var(--line);
  }

  h3 { font: 500 .78rem/1 var(--mono); letter-spacing: .08em;
       text-transform: uppercase; color: var(--dim);
       margin: 1.25rem 0 .1rem; }

  table { border-collapse: collapse; width: 100%; }
  th { text-align: left; font-weight: 400; }
  .num { text-align: right; font-family: var(--mono);
         font-variant-numeric: tabular-nums; white-space: nowrap; }

  .bars th { padding: .32rem .75rem .32rem 0; white-space: nowrap; }
  .bars td:nth-child(2) { width: 58%; padding: .32rem 0; }
  .bars .num { padding-left: .75rem; font-size: .85rem; }
  .track { display: block; height: .5rem; border-radius: 2px;
           background: var(--sunk); overflow: hidden; }
  .bar { display: block; height: 100%; border-radius: 2px;
         background: var(--accent); }
  .bar.is-signal { background: var(--signal); }
  .star { font: 500 .62rem/1 var(--mono); letter-spacing: .1em;
          text-transform: uppercase; color: var(--signal);
          border: 1px solid currentColor; border-radius: 3px;
          padding: .15rem .3rem; margin-left: .5rem; vertical-align: .05em; }

  .rows { background: var(--panel); border: 1px solid var(--line);
          border-radius: 6px; overflow: hidden; }
  .rows tr:nth-child(odd) { background: var(--sunk); }
  .rows th, .rows td { padding: .5rem .85rem; font-size: .9rem; }

  .caveat {
    color: var(--dim); background: var(--panel);
    border: 1px dashed var(--line); border-left: 3px solid var(--signal);
    padding: .85rem 1.1rem; border-radius: 0 6px 6px 0; margin: 0;
    font-size: .9rem;
  }
  .caveat em { color: var(--ink); font-style: normal; font-weight: 500; }
  .empty { color: var(--dim); }

  footer { color: var(--faint); font: 400 .8rem/1.6 var(--mono);
           border-top: 1px solid var(--line); padding-top: 1.25rem; }
  code { font-family: var(--mono); font-size: .92em;
         background: var(--sunk); padding: .1rem .35rem; border-radius: 3px; }
  .scroll { overflow-x: auto; }
  @media (prefers-reduced-motion: reduce) {
    * { animation: none !important; transition: none !important; }
  }
</style>
<main>
  <header class="masthead">
    <span class="eyebrow">AegisFlow</span>
    <h1>__HEADING__</h1>
    <p class="scope">__SCOPE__</p>
  </header>
  __BODY__
  <footer>
    Generated by <code>aegisflow report</code> from __SOURCE__.<br>
    Local only &mdash; nothing in this package sends anything anywhere.
  </footer>
</main>
"""




def document(*, title: str, heading: str, scope: str, source: str,
             body: str) -> str:
    """Fill the shell by replacement, not ``format``.

    The stylesheet is full of braces, and ``format`` would need every one of
    them doubled — a rule nobody remembers on the edit after next.
    """
    out = _TEMPLATE
    for token, value in (
        ("__TITLE__", html.escape(title)),
        ("__HEADING__", html.escape(heading)),
        ("__SCOPE__", html.escape(scope)),
        ("__SOURCE__", html.escape(source)),
        ("__BODY__", body),
    ):
        out = out.replace(token, value)
    return out


__all__ = ["document"]
