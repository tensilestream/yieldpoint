#!/usr/bin/env python3
"""Update the in-repository formula only from an exact release archive digest."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORMULA = ROOT / "Formula" / "yieldpoint.rb"


def replace_once(source: str, pattern: str, replacement: str) -> str:
    updated, count = re.subn(pattern, replacement, source, count=1, flags=re.MULTILINE)
    if count != 1:
        raise SystemExit(f"formula has no unique marker for {pattern!r}")
    return updated


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("version")
    parser.add_argument("sha256")
    parser.add_argument("--formula", type=Path, default=FORMULA)
    args = parser.parse_args()
    if not re.fullmatch(r"\d+\.\d+\.\d+", args.version):
        raise SystemExit("version must be MAJOR.MINOR.PATCH")
    if not re.fullmatch(r"[0-9a-f]{64}", args.sha256):
        raise SystemExit("sha256 must be 64 lowercase hexadecimal characters")
    formula = args.formula.resolve()
    source = formula.read_text(encoding="utf-8")
    source = replace_once(source, r'^  url ".*"$',
                          f'  url "https://github.com/tensilestream/yieldpoint/archive/refs/tags/v{args.version}.tar.gz"')
    source = replace_once(source, r'^  sha256 "[0-9a-f]{64}"$', f'  sha256 "{args.sha256}"')
    formula.write_text(source, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
