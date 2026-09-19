#!/usr/bin/env bash
# Pre-flight for a release. Fails loudly and early; see RELEASING.md.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$PWD"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

step() { printf "\n\033[1m==> %s\033[0m\n" "$1"; }

step "Version agreement"
PYPROJECT_VERSION="$(python3 -c "import tomllib;print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")"
PACKAGE_VERSION="$(python3 -c "import re;print(re.search(r'__version__ = \"([^\"]+)\"', open('yieldpoint/__init__.py').read()).group(1))")"
if [ "$PYPROJECT_VERSION" != "$PACKAGE_VERSION" ]; then
  echo "version drift: pyproject=$PYPROJECT_VERSION package=$PACKAGE_VERSION" >&2
  exit 1
fi
echo "  $PYPROJECT_VERSION"

step "Changelog mentions this version"
grep -q "\[$PYPROJECT_VERSION\]" CHANGELOG.md || { echo "CHANGELOG.md has no [$PYPROJECT_VERSION] entry" >&2; exit 1; }
echo "  ok"

step "Test suite"
python3 -m unittest discover -s tests -t . -q

step "Yieldpoint audits itself"
python3 -m yieldpoint.cli scan yieldpoint --policy .yieldpoint.json --rule dangling_reference \
  --rule boundary_violation --rule export_removed --rule duplicate_implementation \
  --rule file_too_long --rule utility_module
echo "  correctness rules clean"
python3 -m yieldpoint.cli scan yieldpoint --policy .yieldpoint.json 2>/dev/null | tail -6 || true

step "File length limit (RULES.md section 1)"
OVER="$(find yieldpoint -name '*.py' -exec sh -c 'n=$(grep -cve "^\s*$" -e "^\s*#" "$1"); [ "$n" -gt 300 ] && echo "$1 $n"' _ {} \; || true)"
[ -z "$OVER" ] || { echo "over 300 lines:"; echo "$OVER"; exit 1; }
echo "  ok"

step "Build"
rm -rf dist build
python3 -m build >/dev/null
ls -1 dist

step "Clean-room install"
python3 -m venv "$WORK/venv"
"$WORK/venv/bin/pip" install -q dist/*.whl
cd "$WORK"
"$WORK/venv/bin/yieldpoint" --version

mkdir -p demo/tests && cd demo
printf 'def test_total(inv):\n    assert inv.total == 42\n' > tests/test_invoice.py
printf 'def test_total(inv):\n    assert inv.total is not None\n' > weakened.py

if "$WORK/venv/bin/yieldpoint" check --path tests/test_invoice.py \
     --before tests/test_invoice.py --after weakened.py >/dev/null; then
  echo "a weakened assertion was NOT reported" >&2
  exit 1
fi
echo "  weakening detected, exit 1"

"$WORK/venv/bin/yieldpoint" scan . >/dev/null && echo "  clean tree passes, exit 0"

"$WORK/venv/bin/python" -c "
from yieldpoint.verify import verify_change
v = verify_change('def test_x():\n    assert a == 1\n',
                  'def test_x():\n    assert a is not None\n', 'tests/t.py')
assert v.findings and v.findings[0].rule == 'assertion_monotonicity', v
print('  python API works with no dependencies')
"

cd "$ROOT"
printf "\n\033[1;32mRELEASE CHECK PASSED\033[0m  (version %s)\n" "$PYPROJECT_VERSION"
