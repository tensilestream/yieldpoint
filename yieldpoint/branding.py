"""The mark, and the rules about when to show it.

The logo is a stress–strain curve, and the amber dot on it is the product. A
material loaded steadily rises through its elastic region, reaches its **yield
point** — where it stops springing back and deforms for good — and later
fractures. A test suite does the same under an agent's edits: strong, then
quietly weaker, then holding nothing up.

The fracture is obvious; a failing build announces itself. The yield point does
not, and that is the one this tool finds.

**When it is shown is as much a design decision as how it looks.** A banner on
every invocation breaks ``yieldpoint check --json | jq``, floods CI logs, and
corrupts anything reading stdout. So:

- it is written to **stderr**, never stdout, which carries results;
- only when stderr is a terminal, so a pipe or a file gets nothing;
- never with ``--json``, which exists to be parsed;
- never when ``NO_COLOR`` is set, ``TERM`` is ``dumb``, or ``CI`` is present.

Colour follows the same rules. The difference between a tool that feels
established and one that feels noisy is mostly this: knowing when to be quiet.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

NAME = "yieldpoint"
TAGLINE = "find where a test suite stops holding"

#: Graphite ground, steel for structure, amber at the yield point. 256-colour
#: rather than truecolour, because a great many terminals still stop there.
_STEEL = "\033[38;5;67m"
_AMBER = "\033[38;5;173m"
#: Only for a verdict that stops the caller. Muted brick rather than terminal
#: red, so it sits with the steel and amber instead of shouting over them.
_RED = "\033[38;5;167m"
_DIM = "\033[38;5;244m"
_BOLD = "\033[1m"
_RESET = "\033[0m"

#: The curve in three rows, each split so the yield point and the fracture can
#: be picked out in amber while the elastic region stays steel. Written as
#: (steel, amber, steel) rather than as one string, because the whole point of
#: the mark is that one moment on it is different from the rest.
_ROWS = (
    ("   ╭", "●", "╮    "),
    (" ╱  ", " ", " ╲   "),
    ("╱   ", " ", "  ╳  "),
)

#: The plain form, for anywhere that cannot colour.
_MARK = tuple("".join(row).rstrip() for row in _ROWS)


@dataclass(frozen=True)
class Palette:
    """Either real escape codes, or empty strings. Never a conditional."""

    steel: str = ""
    amber: str = ""
    red: str = ""
    dim: str = ""
    bold: str = ""
    reset: str = ""

    @property
    def coloured(self) -> bool:
        return bool(self.reset)


PLAIN = Palette()
COLOUR = Palette(steel=_STEEL, amber=_AMBER, red=_RED, dim=_DIM, bold=_BOLD,
                 reset=_RESET)


def wants_colour(stream=None) -> bool:
    """Whether to colour ``stream``. Conservative on purpose.

    ``NO_COLOR`` is honoured because it is the convention, and ``CI`` because a
    build log full of escape codes is worse than a plain one.
    """
    if os.environ.get("NO_COLOR") or os.environ.get("CI"):
        return False
    if os.environ.get("TERM", "") in ("dumb", ""):
        return False
    target = stream if stream is not None else sys.stderr
    try:
        return bool(target.isatty())
    except (AttributeError, ValueError):
        return False


def palette(stream=None) -> Palette:
    return COLOUR if wants_colour(stream) else PLAIN


def banner(subcommand: str = "", stream=None) -> str:
    """The wordmark and curve, or an empty string when it should stay quiet."""
    paint = palette(stream)
    if not paint.coloured:
        return ""
    curve = _curve(paint)
    lines = [
        curve[0],
        f"{curve[1]}  {paint.bold}{NAME}{paint.reset}",
        f"{curve[2]}  {paint.dim}{TAGLINE}{paint.reset}",
    ]
    if subcommand:
        lines[2] += f"{paint.dim}  ·  {subcommand}{paint.reset}"
    return "\n".join(lines) + "\n"


def _curve(paint: Palette) -> list[str]:
    """The three rows, with the yield point picked out from the elastic region."""
    return [
        f"{paint.steel}{before}{paint.reset}"
        f"{paint.amber}{point}{paint.reset}"
        f"{paint.steel}{after}{paint.reset}"
        for before, point, after in _ROWS
    ]


def show(subcommand: str = "", stream=None) -> None:
    """Print the banner to stderr, if this is a place a banner belongs."""
    target = stream if stream is not None else sys.stderr
    text = banner(subcommand, target)
    if text:
        print(text, file=target)


def mark(paint: Palette | None = None) -> str:
    """The curve alone, for a header that already names the tool."""
    return "\n".join(_curve(paint or palette()))


__all__ = [
    "NAME", "TAGLINE", "Palette", "PLAIN", "COLOUR",
    "palette", "wants_colour", "banner", "show", "mark",
]
