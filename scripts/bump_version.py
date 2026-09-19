#!/usr/bin/env python3
"""Synchronize and bump YieldPoint versions across all packages.

Updates:
- pyproject.toml
- yieldpoint/__init__.py
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = ROOT / "pyproject.toml"
INIT_PATH = ROOT / "yieldpoint" / "__init__.py"

#: Every artifact that declares the version, and the assignment it declares it in.
VERSION_SITES = (
    (PYPROJECT_PATH, "version"),
    (INIT_PATH, "__version__"),
)


def read_current_version() -> str:
    content = PYPROJECT_PATH.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', content, re.MULTILINE)
    if not match:
        raise ValueError(f"Could not find version string in {PYPROJECT_PATH}")
    return match.group(1)


def parse_semver(v: str) -> tuple[int, int, int]:
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)", v)
    if not m:
        raise ValueError(f"Invalid semver version: {v}")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def calculate_bump(current: str, bump_type: str) -> str:
    major, minor, patch = parse_semver(current)
    if bump_type == "major":
        return f"{major + 1}.0.0"
    elif bump_type == "minor":
        return f"{major}.{minor + 1}.0"
    elif bump_type == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise ValueError(f"Unknown bump type: {bump_type}")


def update_version(path: Path, assignment: str, new_version: str) -> None:
    """Rewrite the one `<assignment> = "..."` line in `path`.

    A miss is raised rather than written: silently leaving a file at the old
    version is the drift `--check` exists to catch, and a release script that
    reports success while changing nothing is worse than one that stops.
    """
    content = path.read_text(encoding="utf-8")
    updated, replaced = re.subn(
        rf'^{re.escape(assignment)}\s*=\s*"[^"]+"',
        f'{assignment} = "{new_version}"',
        content,
        count=1,
        flags=re.MULTILINE,
    )
    if not replaced:
        raise SystemExit(f"no `{assignment} = ...` line in {path.relative_to(ROOT)}")
    path.write_text(updated, encoding="utf-8")
    print(f"✓ Updated {path.relative_to(ROOT)} -> {new_version}")


def collect_versions() -> dict[str, str]:
    """Read declared versions from artifacts that carry one."""
    found: dict[str, str] = {"pyproject.toml": read_current_version()}
    if INIT_PATH.exists():
        match = re.search(r'^__version__\s*=\s*"([^"]+)"', INIT_PATH.read_text(encoding="utf-8"), re.MULTILINE)
        found["yieldpoint/__init__.py"] = match.group(1) if match else "unknown"
    return found


def check_versions() -> int:
    """Report divergence between artifacts and change nothing."""
    found = collect_versions()
    expected = found["pyproject.toml"]
    divergent = {name: value for name, value in found.items() if value != expected}
    for name, value in sorted(found.items()):
        marker = "  " if value == expected else "! "
        print(f"{marker}{name}: {value}")
    if divergent:
        print(
            f"\nVersions diverge from pyproject.toml ({expected}). "
            f"Run: python3 scripts/bump_version.py {expected}",
            file=sys.stderr,
        )
        return 1
    print(f"\nAll artifacts agree on {expected}.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Synchronize YieldPoint project versions.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--check",
        action="store_true",
        help="Report version divergence across artifacts and exit 1 if any. Changes nothing.",
    )
    group.add_argument("version", nargs="?", help="Explicit new version (e.g. 0.1.1)")
    group.add_argument("--patch", action="store_true", help="Bump patch version (e.g. 0.1.0 -> 0.1.1)")
    group.add_argument("--minor", action="store_true", help="Bump minor version (e.g. 0.1.0 -> 0.2.0)")
    group.add_argument("--major", action="store_true", help="Bump major version (e.g. 0.1.0 -> 1.0.0)")

    args = parser.parse_args()
    if args.check:
        return check_versions()

    current_version = read_current_version()
    print(f"Current version: {current_version}")

    if args.patch:
        new_version = calculate_bump(current_version, "patch")
    elif args.minor:
        new_version = calculate_bump(current_version, "minor")
    elif args.major:
        new_version = calculate_bump(current_version, "major")
    else:
        new_version = args.version.lstrip("v")
        parse_semver(new_version)

    print(f"Bumping to:      {new_version}\n")

    for path, assignment in VERSION_SITES:
        update_version(path, assignment, new_version)

    print(f"\nAll version markers successfully synchronized to {new_version}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
