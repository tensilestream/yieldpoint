"""What a test and an assertion *look like*, per language.

Separated from lexical.py because the two change for different reasons:
this file changes when a language or framework is added, that one when
there is a better way to read what is found. It also keeps both inside the
length limit this project enforces on everyone else.

Every pattern here is deliberately timid. A construct it does not
recognise yields nothing, and nothing is reported as unverified rather
than as clean.
"""

from __future__ import annotations

import re

from .relation import Relation

#: Suffixes read lexically. Python is absent on purpose — it has an exact path.
SUFFIXES = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".java", ".kt", ".go",
            ".rs", ".cs", ".rb", ".php", ".swift")

#: ``it("...")``, ``test("...")``, ``@Test void name()``, ``func TestName(``.
TEST_DECL = re.compile(
    r"""(?:
        \b(?:it|test)\s*(?:\.\w+)?\s*\(\s*(?P<quote>["'`])(?P<name>[^"'`]{1,200})(?P=quote)
      | @Test[\s\S]{0,120}?\b(?:public\s+|private\s+)?\w[\w<>\[\]]*\s+(?P<jname>\w+)\s*\(
      | \bfun\s+(?P<kname>`[^`]+`|\w+)\s*\([^)]*\)\s*(?=\{)
      | \bfunc\s+(?P<gname>Test\w+)\s*\(
      | \#\[test\][\s\S]{0,120}?\bfn\s+(?P<rname>\w+)\s*\(
      | \[(?:Fact|Test|TestMethod|Theory)\][\s\S]{0,160}?
          \b(?:public\s+|private\s+|internal\s+)?(?:async\s+)?
          [\w<>\[\]]+\s+(?P<csname>\w+)\s*\(
      | \bfunc\s+(?P<swname>test\w+)\s*\(
      | \b(?:def)\s+(?P<rbname>test_\w+)
      | \bpublic\s+function\s+(?P<phpname>test\w+)\s*\(
    )""",
    re.VERBOSE,
)

#: ``expect(x).toBe(1)``, ``assertThat(x).isEqualTo(1)``, ``x.should.equal(1)``.
FLUENT = re.compile(
    r"\b(?:expect|assertThat|assert_that|require)\s*\(\s*(?P<subject>.+?)\s*\)"
    r"(?P<chain>(?:\s*\.\s*\w+(?:\s*\([^()]*\))?)+)",
    re.DOTALL,
)

#: ``assertEquals(expected, actual)``, ``assert.equal(a, b)``, ``assert.Equal(t, a, b)``.
CALL = re.compile(
    r"\b(?:(?:assert|Assert|XCTAssert)\s*\.\s*)?"
    r"(?P<name>assert[A-Za-z_]*|XCTAssert[A-Za-z]*|refute[A-Za-z_]*"
    r"|Are[A-Za-z]+|Is[A-Za-z]+|Equal|NotEqual|True|False|Nil|NotNil"
    r"|Throws[A-Za-z]*|Contains|Greater|Less)"
    r"!?\s*\(\s*(?P<args>[^;]{0,400}?)\s*\)\s*[;\n]"
)

#: Go's standard library has no assertion API. The idiom is a guard that fails
#: the test, and the assertion is the *negation* of the guard:
#: ``if got != want { t.Errorf(...) }`` asserts ``got == want``. Missing this
#: means missing most Go tests ever written, since testify is a dependency many
#: projects deliberately avoid.
GO_GUARD = re.compile(
    r"\bif\s+(?P<cond>[^{;\n]{1,200}?)\s*\{[^{}]{0,400}?"
    r"\bt\s*\.\s*(?:Fatal|Fatalf|Error|Errorf)\s*\(",
    re.DOTALL,
)

#: Guard operator -> what passing the test therefore proves. Inverted on
#: purpose: the guard describes failure, the assertion describes success.
GO_INVERSE = {
    "!=": Relation.EQ,
    "==": Relation.COMPARISON,
    "<": Relation.COMPARISON,
    ">": Relation.COMPARISON,
    "<=": Relation.COMPARISON,
    ">=": Relation.COMPARISON,
}

#: Ruby lets a method call omit its parentheses, and Minitest's own examples do:
#: ``assert_equal 42, total``. Applied only to Ruby, because a bare word
#: followed by arguments means something different in every other language here.
_RUBYCALL = re.compile(
    r"^\s*(?P<name>assert_\w+|refute_\w+)\s+(?!\()(?P<args>[^\n]{1,200})$",
    re.MULTILINE,
)

MAX_SUBJECT = 120


#: Declaration groups, in the order a name is looked for. One per language
#: family; a match sets exactly one of them.
NAME_GROUPS = ("name", "jname", "kname", "gname", "rname", "csname",
                "swname", "rbname", "phpname")


#: Families that put the value under test *first*: ``assert_eq!(got, 42)``,
#: ``XCTAssertEqual(got, 42)``. JUnit and xUnit put the expectation first, so
#: taking the last argument everywhere reads the literal as the subject and
#: discards the assertion.
SUBJECT_FIRST = ("assert_eq", "assert_ne", "debug_assert", "assert_matches",
                  "XCTAssert", "refute", "assert_equal", "assert_nil",
                  "assert_includes", "assert_instance_of", "refute_equal",
                  "refute_nil")


#: Ruby keywords that open a block needing its own ``end``. ``do`` is matched
#: separately because it may trail a method call on the same line.
RUBY_OPENERS = ("def ", "if ", "unless ", "case ", "begin", "while ", "until ",
                 "class ", "module ")


__all__ = [
    "CALL", "FLUENT", "GO_GUARD", "GO_INVERSE", "MAX_SUBJECT",
    "NAME_GROUPS", "RUBY_CALL", "RUBY_OPENERS", "SUBJECT_FIRST",
    "SUFFIXES", "TEST_DECL",
]
