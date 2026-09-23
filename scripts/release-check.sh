#!/usr/bin/env bash
# Pre-flight for a release. Fails loudly and early; see RELEASING.md.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$PWD"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

step() { printf "\n\033[1m==> %s\033[0m\n" "$1"; }

step "Version agreement"
python3 scripts/bump_version.py --check
PYPROJECT_VERSION="$(python3 -c "import tomllib;print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")"
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
PACKAGE_DIST="$WORK/dist"
python3 -m build --outdir "$PACKAGE_DIST" >/dev/null
ls -1 "$PACKAGE_DIST"

step "Node SDK"
if [ -d sdk/node ]; then
  npm --prefix sdk/node ci
  npm --prefix sdk/node test
  (cd sdk/node && npm pack --dry-run)
fi

step "Java SDK"
if [ -d sdk/java ]; then
  mvn -B -f sdk/java/pom.xml install
  mkdir -p "$WORK/java-consumer/src/main/java/consumer"
  cat > "$WORK/java-consumer/pom.xml" <<EOF
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>release.check</groupId><artifactId>java-consumer</artifactId><version>1</version>
  <properties><maven.compiler.release>17</maven.compiler.release></properties>
  <dependencies><dependency><groupId>io.github.tensilestream</groupId><artifactId>yieldpoint-langgraph4j</artifactId><version>$PYPROJECT_VERSION</version></dependency></dependencies>
</project>
EOF
  cat > "$WORK/java-consumer/src/main/java/consumer/Consumer.java" <<'EOF'
package consumer;
import io.github.tensilestream.yieldpoint.langgraph4j.YieldpointRouter;
public final class Consumer { public static void main(String[] args) { new YieldpointRouter(); } }
EOF
  mvn -B -f "$WORK/java-consumer/pom.xml" package
  echo "  packaged Java SDK imports in a clean consumer"
fi

step "Clean-room install"
python3 -m venv "$WORK/venv"
"$WORK/venv/bin/pip" install -q "$PACKAGE_DIST"/*.whl
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
