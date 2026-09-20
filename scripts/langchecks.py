"""One test file per language, in each state a contract rule looks for.

The cross product of languages and checks is mostly empty, and honestly so:
structure and refactor rules need a syntax tree, and this package ships a
parser for Python only. The contract rules are the ones that work everywhere,
because a weakened assertion has a shape even a regular expression can see.

Each entry is the same test written six ways: pinned, weakened, vacuous,
emptied, skipped, and swallowed. What a language cannot express is left None
rather than faked — Go has no skip decorator, and pretending otherwise would
report a rule as covered where nothing was tested.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LangCase:
    language: str
    path: str
    strong: str
    weak: str | None = None
    vacuous: str | None = None
    empty: str | None = None
    skipped: str | None = None
    swallowed: str | None = None


CASES = (
    LangCase(
        "Python", "tests/test_total.py",
        strong="def test_total():\n    assert total == 42\n",
        weak="def test_total():\n    assert total is not None\n",
        vacuous="def test_total():\n    assert True\n",
        empty="def test_total():\n    pass\n",
        skipped="import pytest\n\n\n@pytest.mark.skip('flaky')\n"
                "def test_total():\n    assert total == 42\n",
        swallowed="def test_total():\n    try:\n        assert total == 42\n"
                  "    except AssertionError:\n        pass\n",
    ),
    LangCase(
        "JavaScript", "src/total.test.js",
        strong="test('total', () => {\n  expect(total).toBe(42);\n});\n",
        weak="test('total', () => {\n  expect(total).toBeDefined();\n});\n",
        vacuous="test('total', () => {\n  expect(true).toBe(true);\n});\n",
        empty="test('total', () => {\n});\n",
        skipped="test.skip('total', () => {\n  expect(total).toBe(42);\n});\n",
    ),
    LangCase(
        "TypeScript", "src/total.test.ts",
        strong="test('total', () => {\n  expect(total).toBe(42);\n});\n",
        weak="test('total', () => {\n  expect(total).toBeDefined();\n});\n",
        vacuous="test('total', () => {\n  expect(true).toBe(true);\n});\n",
        empty="test('total', () => {\n});\n",
        skipped="test.skip('total', () => {\n  expect(total).toBe(42);\n});\n",
    ),
    LangCase(
        "Java", "src/test/java/TotalTest.java",
        strong="class TotalTest {\n  @Test void total() {\n"
               "    assertEquals(42, total);\n  }\n}\n",
        weak="class TotalTest {\n  @Test void total() {\n"
             "    assertNotNull(total);\n  }\n}\n",
        vacuous="class TotalTest {\n  @Test void total() {\n"
                "    assertTrue(true);\n  }\n}\n",
        empty="class TotalTest {\n  @Test void total() {\n  }\n}\n",
        skipped="class TotalTest {\n  @Disabled\n  @Test void total() {\n"
                "    assertEquals(42, total);\n  }\n}\n",
    ),
    LangCase(
        "Kotlin", "src/test/kotlin/TotalTest.kt",
        strong="class TotalTest {\n  @Test fun total() {\n"
               "    assertEquals(42, total)\n  }\n}\n",
        weak="class TotalTest {\n  @Test fun total() {\n"
             "    assertNotNull(total)\n  }\n}\n",
        vacuous="class TotalTest {\n  @Test fun total() {\n"
                "    assertTrue(true)\n  }\n}\n",
        empty="class TotalTest {\n  @Test fun total() {\n  }\n}\n",
    ),
    LangCase(
        "Go", "pkg/total_test.go",
        strong='func TestTotal(t *testing.T) {\n\tif total != 42 {\n'
               '\t\tt.Fatal("bad")\n\t}\n}\n',
        weak='func TestTotal(t *testing.T) {\n\tif !total {\n'
             '\t\tt.Fatal("bad")\n\t}\n}\n',
        empty='func TestTotal(t *testing.T) {\n}\n',
        skipped='func TestTotal(t *testing.T) {\n\tt.Skip("flaky")\n'
                '\tif total != 42 {\n\t\tt.Fatal("bad")\n\t}\n}\n',
    ),
    LangCase(
        "Rust", "src/tests/total_test.rs",
        strong="#[test]\nfn total_is_42() {\n    assert_eq!(total, 42);\n}\n",
        weak="#[test]\nfn total_is_42() {\n    assert!(total);\n}\n",
        empty="#[test]\nfn total_is_42() {\n}\n",
        skipped="#[test]\n#[ignore]\nfn total_is_42() {\n"
                "    assert_eq!(total, 42);\n}\n",
    ),
    LangCase(
        "C#", "Tests/TotalTest.cs",
        strong="public class TotalTest {\n  [Fact]\n  public void Total() {\n"
               "    Assert.Equal(42, total);\n  }\n}\n",
        weak="public class TotalTest {\n  [Fact]\n  public void Total() {\n"
             "    Assert.NotNull(total);\n  }\n}\n",
        empty="public class TotalTest {\n  [Fact]\n  public void Total() {\n  }\n}\n",
    ),
    LangCase(
        "Ruby", "test/total_test.rb",
        strong="class TotalTest < Minitest::Test\n  def test_total\n"
               "    assert_equal 42, total\n  end\nend\n",
        weak="class TotalTest < Minitest::Test\n  def test_total\n"
             "    refute_nil total\n  end\nend\n",
        empty="class TotalTest < Minitest::Test\n  def test_total\n  end\nend\n",
    ),
    LangCase(
        "PHP", "tests/TotalTest.php",
        strong="<?php\nclass TotalTest extends TestCase {\n"
               "  public function testTotal() {\n    $this->assertSame(42, $total);\n  }\n}\n",
        weak="<?php\nclass TotalTest extends TestCase {\n"
             "  public function testTotal() {\n    $this->assertNotNull($total);\n  }\n}\n",
        empty="<?php\nclass TotalTest extends TestCase {\n"
              "  public function testTotal() {\n  }\n}\n",
    ),
    LangCase(
        "Swift", "Tests/TotalTests.swift",
        strong="class TotalTests: XCTestCase {\n  func testTotal() {\n"
               "    XCTAssertEqual(total, 42)\n  }\n}\n",
        weak="class TotalTests: XCTestCase {\n  func testTotal() {\n"
             "    XCTAssertNotNil(total)\n  }\n}\n",
        empty="class TotalTests: XCTestCase {\n  func testTotal() {\n  }\n}\n",
    ),
    LangCase(
        "Elixir", "test/total_test.exs",
        strong='test "total is 42" do\n  assert total == 42\nend\n',
        weak='test "total is 42" do\n  assert total\nend\n',
        empty='test "total is 42" do\nend\n',
    ),
)

#: What each state should provoke. None means the language cannot express it.
STATES = (
    ("weak", "assertion_monotonicity"),
    ("vacuous", "vacuous_assertion"),
    ("empty", "empty_test"),
    ("skipped", "skip_marker"),
    ("swallowed", "disabled_assertion"),
)

__all__ = ["CASES", "STATES", "LangCase"]
