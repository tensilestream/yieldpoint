"""What Yieldpoint reads, per language, measured rather than claimed.

    python scripts/language_matrix.py            # print
    python scripts/language_matrix.py --markdown # the table for the README

Each row runs a real weakening and a real legitimate edit through the verifier.
A language is only listed as supported if the weakening is reported *and* the
legitimate edit is not — half of that is not support, it is noise.

The tier matters more than the tick. Exact analysis can block a commit; lexical
analysis can only advise, because ``Finding.__post_init__`` refuses to let a
non-exact finding block anything.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from yieldpoint.core.verdict import Confidence, Status  # noqa: E402
from yieldpoint.verify import verify_change  # noqa: E402

POLICY = {
    "test_contract": {
        "protected_patterns": [
            "**/tests/**", "**/test/**", "**/test_*.py", "**/*_test.*",
            "**/*.test.*", "**/*Test.*", "**/*Tests.*", "**/*Spec.*",
        ],
        "assertion_monotonicity": "block",
    }
}


@dataclass(frozen=True)
class Case:
    language: str
    framework: str
    path: str
    strong: str
    weak: str
    """The same test with its assertion downgraded."""


CASES = (
    Case("Python", "pytest / unittest", "tests/test_total.py",
         "def test_total():\n    assert total == 42\n",
         "def test_total():\n    assert total\n"),
    Case("JavaScript", "Jest / Vitest / Mocha", "src/total.test.js",
         "test('total', () => {\n  expect(total).toBe(42);\n});\n",
         "test('total', () => {\n  expect(total).toBeDefined();\n});\n"),
    Case("TypeScript", "Jest / Vitest", "src/total.test.ts",
         "test('total', () => {\n  expect(total).toBe(42);\n});\n",
         "test('total', () => {\n  expect(total).toBeDefined();\n});\n"),
    Case("Java", "JUnit / AssertJ", "src/test/java/TotalTest.java",
         "class TotalTest {\n  @Test void total() {\n"
         "    assertEquals(42, total);\n  }\n}\n",
         "class TotalTest {\n  @Test void total() {\n"
         "    assertNotNull(total);\n  }\n}\n"),
    Case("Kotlin", "JUnit", "src/test/kotlin/TotalTest.kt",
         "class TotalTest {\n  @Test fun total() {\n"
         "    assertEquals(42, total)\n  }\n}\n",
         "class TotalTest {\n  @Test fun total() {\n"
         "    assertNotNull(total)\n  }\n}\n"),
    Case("Go", "stdlib guards / testify", "pkg/total_test.go",
         'func TestTotal(t *testing.T) {\n\tif total != 42 {\n\t\tt.Fatal("bad")\n\t}\n}\n',
         'func TestTotal(t *testing.T) {\n\tif !total {\n\t\tt.Fatal("bad")\n\t}\n}\n'),
    Case("Rust", "built-in test harness", "src/tests/total_test.rs",
         "#[test]\nfn total_is_42() {\n    assert_eq!(total, 42);\n}\n",
         "#[test]\nfn total_is_42() {\n    assert!(total);\n}\n"),
    Case("C#", "xUnit / NUnit / MSTest", "Tests/TotalTest.cs",
         "public class TotalTest {\n  [Fact]\n  public void Total() {\n"
         "    Assert.Equal(42, total);\n  }\n}\n",
         "public class TotalTest {\n  [Fact]\n  public void Total() {\n"
         "    Assert.NotNull(total);\n  }\n}\n"),
    Case("Ruby", "Minitest", "test/total_test.rb",
         "class TotalTest < Minitest::Test\n  def test_total\n"
         "    assert_equal 42, total\n  end\nend\n",
         "class TotalTest < Minitest::Test\n  def test_total\n"
         "    refute_nil total\n  end\nend\n"),
    Case("PHP", "PHPUnit", "tests/TotalTest.php",
         "<?php\nclass TotalTest extends TestCase {\n"
         "  public function testTotal() {\n    $this->assertSame(42, $total);\n  }\n}\n",
         "<?php\nclass TotalTest extends TestCase {\n"
         "  public function testTotal() {\n    $this->assertNotNull($total);\n  }\n}\n"),
    Case("Swift", "XCTest", "Tests/TotalTests.swift",
         "class TotalTests: XCTestCase {\n  func testTotal() {\n"
         "    XCTAssertEqual(total, 42)\n  }\n}\n",
         "class TotalTests: XCTestCase {\n  func testTotal() {\n"
         "    XCTAssertNotNil(total)\n  }\n}\n"),
    Case("Elixir", "ExUnit", "test/total_test.exs",
         "test \"total\" do\n  assert total == 42\nend\n",
         "test \"total\" do\n  assert total\nend\n"),
)


@dataclass(frozen=True)
class Row:
    language: str
    framework: str
    caught: bool
    quiet_on_legitimate: bool
    tier: str
    detail: str

    @property
    def supported(self) -> bool:
        """Catching a weakening is only half. Staying quiet on real work is
        the other half, and the half people actually notice."""
        return self.caught and self.quiet_on_legitimate


def measure(case: Case) -> Row:
    weakened = verify_change(case.strong, case.weak, case.path, POLICY)
    unchanged = verify_change(case.strong, case.strong, case.path, POLICY)

    caught = any(f.rule == "assertion_monotonicity" for f in weakened.findings)
    confidences = {f.confidence for f in weakened.findings}
    if not caught:
        tier = "none"
    elif Confidence.EXACT in confidences:
        tier = "exact"
    else:
        tier = "lexical"

    detail = ""
    if not caught:
        detail = (weakened.skipped[0].split(": ", 1)[-1][:60]
                  if weakened.skipped else weakened.status.value)

    return Row(
        language=case.language, framework=case.framework, caught=caught,
        quiet_on_legitimate=not unchanged.findings, tier=tier, detail=detail,
    )


TIER_NOTE = {
    "exact": "blocks",
    "lexical": "warns",
    "none": "not read",
}


def markdown(rows: list[Row]) -> str:
    lines = [
        "| Language | Frameworks read | Weakening caught | Quiet on legitimate | Can gate a commit |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        caught = "yes" if row.caught else f"**no** — {row.detail or 'no analyser'}"
        quiet = "yes" if row.quiet_on_legitimate else "**no**"
        gate = {"exact": "**yes**", "lexical": "no — warns only",
                "none": "no"}[row.tier]
        lines.append(f"| {row.language} | {row.framework} | {caught} | "
                     f"{quiet} | {gate} |")
    return "\n".join(lines)


def plain(rows: list[Row]) -> str:
    lines = [f"  {'language':12} {'caught':>7} {'quiet':>6} {'tier':>8}  frameworks"]
    for row in rows:
        lines.append(
            f"  {row.language:12} {'yes' if row.caught else 'NO':>7} "
            f"{'yes' if row.quiet_on_legitimate else 'NO':>6} "
            f"{row.tier:>8}  {row.framework}")
    exact = sum(1 for r in rows if r.tier == "exact")
    lexical = sum(1 for r in rows if r.tier == "lexical")
    lines.append("")
    lines.append(f"  {exact + lexical}/{len(rows)} languages read; "
                 f"{exact} can block a commit, {lexical} advise only")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args()

    rows = [measure(case) for case in CASES]
    print(markdown(rows) if args.markdown else plain(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
