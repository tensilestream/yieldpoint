"""Which assertion spellings mean what.

Pure data, separated from the AST logic in recognise.py because the two change
for different reasons: this file grows when a framework adds a spelling, that one
only when the shape of the analysis changes.

Names are **folded** — `is_equal_to`, `isEqualTo` and `IsEqualTo` all reduce to
`isequalto` — so a single table serves snake_case and camelCase ecosystems alike.
"""

from __future__ import annotations

import ast

from .relation import Relation


def fold(name: str) -> str:
    """Normalise a method name so one entry covers every casing convention."""
    return name.replace("_", "").lower()


# unittest/pytest method name -> the relation it asserts.
METHOD_RELATIONS: dict[str, Relation] = {
    # Rust: `assert_eq!`, `assert_ne!`, `assert!`. The bang is stripped before
    # lookup, so the name here is the macro without it.
    "assert_eq": Relation.EQ,
    "assert_ne": Relation.COMPARISON,
    "assert_matches": Relation.MEMBERSHIP,
    "debug_assert_eq": Relation.EQ,
    "debug_assert": Relation.TRUTHY,
    # C# / xUnit, NUnit, MSTest.
    "AreEqual": Relation.EQ,
    "AreNotEqual": Relation.COMPARISON,
    "AreSame": Relation.EQ,
    "IsTrue": Relation.TRUTHY,
    "IsFalse": Relation.TRUTHY,
    "IsNull": Relation.EQ,
    "IsNotNull": Relation.NON_NULL,
    "IsInstanceOf": Relation.MEMBERSHIP,
    "Contains": Relation.MEMBERSHIP,
    "Throws": Relation.RAISES,
    "ThrowsAsync": Relation.RAISES,
    "IsEmpty": Relation.EQ,
    "Greater": Relation.COMPARISON,
    "Less": Relation.COMPARISON,
    # Ruby / RSpec and Minitest.
    "assert_equal": Relation.EQ,
    "assert_nil": Relation.EQ,
    "refute_nil": Relation.NON_NULL,
    "assert_includes": Relation.MEMBERSHIP,
    "assert_raises": Relation.RAISES,
    "assert_instance_of": Relation.MEMBERSHIP,
    "refute_equal": Relation.COMPARISON,
    # PHP / PHPUnit.
    "assertSame": Relation.EQ,
    "assertNotSame": Relation.COMPARISON,
    "assertStringContainsString": Relation.MEMBERSHIP,
    # Swift / XCTest.
    "XCTAssertEqual": Relation.EQ,
    "XCTAssertNotEqual": Relation.COMPARISON,
    "XCTAssertTrue": Relation.TRUTHY,
    "XCTAssertFalse": Relation.TRUTHY,
    "XCTAssertNil": Relation.EQ,
    "XCTAssertNotNil": Relation.NON_NULL,
    "XCTAssertThrowsError": Relation.RAISES,
    "XCTAssert": Relation.TRUTHY,

    "assertEqual": Relation.EQ, "assertEquals": Relation.EQ,
    "assertAlmostEqual": Relation.EQ, "assertIs": Relation.EQ,
    "assertIsNone": Relation.EQ, "assertDictEqual": Relation.EQ,
    "assertListEqual": Relation.EQ, "assertSetEqual": Relation.EQ,
    "assertTupleEqual": Relation.EQ, "assertMultiLineEqual": Relation.EQ,
    "assertCountEqual": Relation.EQ, "assertSequenceEqual": Relation.EQ,
    "assertNotEqual": Relation.COMPARISON, "assertIsNot": Relation.COMPARISON,
    "assertGreater": Relation.COMPARISON, "assertGreaterEqual": Relation.COMPARISON,
    "assertLess": Relation.COMPARISON, "assertLessEqual": Relation.COMPARISON,
    "assertRegex": Relation.COMPARISON, "assertNotAlmostEqual": Relation.COMPARISON,
    "assertIn": Relation.MEMBERSHIP, "assertNotIn": Relation.MEMBERSHIP,
    "assertIsInstance": Relation.MEMBERSHIP, "assertNotIsInstance": Relation.MEMBERSHIP,
    "assertRaises": Relation.RAISES, "assertRaisesRegex": Relation.RAISES,
    "assertWarns": Relation.RAISES, "assertLogs": Relation.RAISES,
    "assertTrue": Relation.TRUTHY, "assertFalse": Relation.TRUTHY,
    "assertIsNotNone": Relation.NON_NULL,
    # JUnit and Node's assert module. Same shapes, different names.
    "assertNotNull": Relation.NON_NULL, "assertNull": Relation.EQ,
    "assertSame": Relation.EQ, "assertNotSame": Relation.COMPARISON,
    "assertArrayEquals": Relation.EQ, "assertIterableEquals": Relation.EQ,
    "assertLinesMatch": Relation.EQ, "assertThrows": Relation.RAISES,
    "assertDoesNotThrow": Relation.RAISES, "assertTimeout": Relation.RAISES,
}

COMPARE_RELATIONS: dict[type[ast.cmpop], Relation] = {
    ast.Eq: Relation.EQ, ast.Is: Relation.EQ,
    ast.NotEq: Relation.COMPARISON, ast.IsNot: Relation.COMPARISON,
    ast.Lt: Relation.COMPARISON, ast.LtE: Relation.COMPARISON,
    ast.Gt: Relation.COMPARISON, ast.GtE: Relation.COMPARISON,
    ast.In: Relation.MEMBERSHIP, ast.NotIn: Relation.MEMBERSHIP,
}

ASSERT_CALL_PREFIXES = ("assert", "check", "verify", "expect", "should")

#: Functions that open a fluent assertion chain. Style is a project's choice, so
#: `assert_that(x).is_equal_to(y)` must be understood as well as `assert x == y`.
FLUENT_ROOTS = (
    "assert_that", "assertThat", "expect", "expects", "should", "should_",
    "require", "check_that", "verify_that", "assume_that", "that",
)

#: Chain links that negate the assertion, weakening an exact claim to a bound.
NEGATIONS = frozenset({"not", "not_", "never", "isnot", "donot", "doesnot"})


def _unusedfold(name: str) -> str:
    """`is_equal_to`, `isEqualTo` and `IsEqualTo` all fold to `isequalto`.

    One table then covers snake_case and camelCase, which is what lets the same
    relation map serve assertpy, AssertJ, Kotest, Chai and Jest.
    """
    return name.replace("_", "").lower()


#: Terminal method of a fluent chain -> the relation it asserts, folded.
FLUENT_RELATIONS: dict[str, Relation] = {
    fold(name): relation
    for name, relation in {
        # exact value
        "is_equal_to": Relation.EQ, "isEqualTo": Relation.EQ, "to_be": Relation.EQ,
        "toBe": Relation.EQ, "to_equal": Relation.EQ, "toEqual": Relation.EQ,
        "toStrictEqual": Relation.EQ, "equals": Relation.EQ, "shouldBe": Relation.EQ,
        "is_close_to": Relation.EQ, "isCloseTo": Relation.EQ, "toBeCloseTo": Relation.EQ,
        "is_same_as": Relation.EQ, "isSameAs": Relation.EQ, "is_none": Relation.EQ,
        "isNull": Relation.EQ, "toBeNull": Relation.EQ, "is_empty": Relation.EQ,
        # bounds and inequality
        "is_greater_than": Relation.COMPARISON, "isGreaterThan": Relation.COMPARISON,
        "is_less_than": Relation.COMPARISON, "isLessThan": Relation.COMPARISON,
        "toBeGreaterThan": Relation.COMPARISON, "toBeLessThan": Relation.COMPARISON,
        "is_not_equal_to": Relation.COMPARISON, "isNotEqualTo": Relation.COMPARISON,
        # Go, testify. Same shape, different casing, so the fold covers it.
        "Equal": Relation.EQ, "EqualValues": Relation.EQ, "Exactly": Relation.EQ,
        "Nil": Relation.EQ, "Zero": Relation.EQ,
        "NotEqual": Relation.COMPARISON, "Greater": Relation.COMPARISON,
        "Less": Relation.COMPARISON, "NotZero": Relation.COMPARISON,
        "Contains": Relation.MEMBERSHIP, "ElementsMatch": Relation.MEMBERSHIP,
        "IsType": Relation.MEMBERSHIP, "Len": Relation.MEMBERSHIP,
        "Panics": Relation.RAISES, "Error": Relation.RAISES, "NoError": Relation.RAISES,
        "True": Relation.TRUTHY, "False": Relation.TRUTHY,
        "NotNil": Relation.NON_NULL, "NotEmpty": Relation.NON_NULL,
        "is_between": Relation.COMPARISON, "isBetween": Relation.COMPARISON,
        "matches": Relation.COMPARISON, "toMatch": Relation.COMPARISON,
        "startsWith": Relation.COMPARISON, "starts_with": Relation.COMPARISON,
        # set membership and type
        "contains": Relation.MEMBERSHIP, "toContain": Relation.MEMBERSHIP,
        "containsAll": Relation.MEMBERSHIP, "is_in": Relation.MEMBERSHIP,
        "isIn": Relation.MEMBERSHIP, "is_instance_of": Relation.MEMBERSHIP,
        "isInstanceOf": Relation.MEMBERSHIP, "toBeInstanceOf": Relation.MEMBERSHIP,
        "has_item": Relation.MEMBERSHIP, "containsKey": Relation.MEMBERSHIP,
        # behaviour
        "raises": Relation.RAISES, "to_raise": Relation.RAISES, "toThrow": Relation.RAISES,
        "isThrownBy": Relation.RAISES, "throws": Relation.RAISES,
        # truthiness
        "is_true": Relation.TRUTHY, "isTrue": Relation.TRUTHY, "is_false": Relation.TRUTHY,
        "isFalse": Relation.TRUTHY, "toBeTruthy": Relation.TRUTHY,
        "toBeFalsy": Relation.TRUTHY, "is_ok": Relation.TRUTHY,
        # mere existence
        "is_not_none": Relation.NON_NULL, "isNotNull": Relation.NON_NULL,
        "toBeDefined": Relation.NON_NULL, "is_not_empty": Relation.NON_NULL,
        "isNotEmpty": Relation.NON_NULL, "exists": Relation.NON_NULL,
        # Chai spells the relation without a prefix: expect(x).to.equal(3)
        "equal": Relation.EQ, "eql": Relation.EQ, "deep": Relation.EQ,
        "above": Relation.COMPARISON, "below": Relation.COMPARISON,
        "include": Relation.MEMBERSHIP, "members": Relation.MEMBERSHIP,
        "property": Relation.MEMBERSHIP, "throw": Relation.RAISES,
        "ok": Relation.TRUTHY, "empty": Relation.EQ,
        "true": Relation.TRUTHY, "false": Relation.TRUTHY,
        "null": Relation.EQ, "undefined": Relation.EQ, "exist": Relation.NON_NULL,
    }.items()
}

#: Matcher-style: `assert_that(x, equal_to(3))` (Hamcrest and its ports).
MATCHER_RELATIONS: dict[str, Relation] = {
    fold(name): relation
    for name, relation in {
        "equal_to": Relation.EQ, "equalTo": Relation.EQ, "same_instance": Relation.EQ,
        "close_to": Relation.EQ, "none": Relation.EQ, "is_": Relation.EQ,
        "greater_than": Relation.COMPARISON, "less_than": Relation.COMPARISON,
        "not_": Relation.COMPARISON, "is_not": Relation.COMPARISON,
        "has_item": Relation.MEMBERSHIP, "has_items": Relation.MEMBERSHIP,
        "contains": Relation.MEMBERSHIP, "instance_of": Relation.MEMBERSHIP,
        "has_key": Relation.MEMBERSHIP, "has_length": Relation.MEMBERSHIP,
        "calling": Relation.RAISES, "raises": Relation.RAISES,
        "not_none": Relation.NON_NULL, "is_not_none": Relation.NON_NULL,
    }.items()
}
_SKIP_MARKERS = ("skip", "xfail", "skipif", "skipunless", "expectedfailure")
