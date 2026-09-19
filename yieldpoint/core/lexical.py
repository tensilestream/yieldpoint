"""Finding tests and assertions without a parser for the language.

Python is analysed exactly, because Python ships a parser. Everything else
would need one per language, and this package has no runtime dependencies on
purpose — so those are read **lexically**: test blocks located by their
declaration, extents found by counting braces, assertions matched by shape.

That is weaker, and the weakness is encoded rather than described. Findings
derived here carry :attr:`Confidence.LEXICAL`, and ``Finding.__post_init__``
refuses to let a non-exact finding block anything. A lexical analyser can tell
an agent it weakened a test; it cannot stop a build.

**It is deliberately timid.** A construct it does not recognise yields nothing,
and a file where nothing is recognised is reported as unverified rather than
as clean. Under-reporting is a gap; over-reporting is a false accusation about
somebody's code, and only one of those is recoverable.

What it reads today: Jest, Vitest, Mocha with Chai, and plain `assert` in
JavaScript and TypeScript; JUnit and AssertJ in Java and Kotlin; testify in Go.
The relation tables are shared with the Python path (spellings.py), so a
framework added there is understood here too.
"""

from __future__ import annotations

import re

from .recognise import Assertion
from .relation import Relation
from .spellings import FLUENT_RELATIONS, METHOD_RELATIONS, NEGATIONS, fold

#: Suffixes read lexically. Python is absent on purpose — it has an exact path.
SUFFIXES = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".java", ".kt", ".go")

#: ``it("...")``, ``test("...")``, ``@Test void name()``, ``func TestName(``.
_TEST_DECL = re.compile(
    r"""(?:
        \b(?:it|test)\s*(?:\.\w+)?\s*\(\s*(?P<quote>["'`])(?P<name>[^"'`]{1,200})(?P=quote)
      | @Test[\s\S]{0,120}?\b(?:public\s+|private\s+)?\w[\w<>\[\]]*\s+(?P<jname>\w+)\s*\(
      | \bfun\s+(?P<kname>`[^`]+`|\w+)\s*\([^)]*\)\s*(?=\{)
      | \bfunc\s+(?P<gname>Test\w+)\s*\(
    )""",
    re.VERBOSE,
)

#: ``expect(x).toBe(1)``, ``assertThat(x).isEqualTo(1)``, ``x.should.equal(1)``.
_FLUENT = re.compile(
    r"\b(?:expect|assertThat|assert_that|require)\s*\(\s*(?P<subject>.+?)\s*\)"
    r"(?P<chain>(?:\s*\.\s*\w+(?:\s*\([^()]*\))?)+)",
    re.DOTALL,
)

#: ``assertEquals(expected, actual)``, ``assert.equal(a, b)``, ``assert.Equal(t, a, b)``.
_CALL = re.compile(
    r"\b(?:assert\s*\.\s*)?(?P<name>assert[A-Za-z]*|Equal|NotEqual|True|False|Nil|NotNil)"
    r"\s*\(\s*(?P<args>[^;]{0,400}?)\s*\)\s*[;\n]"
)

_MAX_SUBJECT = 120


def reads(path: str) -> bool:
    return path.endswith(SUFFIXES)


def extract(source: str, *, filename: str = "<source>") -> tuple:
    """Return ``(tests, recognised)`` for one file.

    ``recognised`` is False when nothing was understood, which the caller turns
    into "unverified" rather than "clean".
    """
    from .assertions import TestCase

    blocks = list(_blocks(source))
    if not blocks:
        return (), False

    cases = []
    understood = False
    for name, start, body, line in blocks:
        assertions = tuple(_assertions(body, line))
        understood = understood or bool(assertions)
        cases.append(TestCase(
            qualname=name,
            line=line,
            assertions=assertions,
            is_empty=not body.strip(),
            body_hash=_shape(body),
        ))
    del filename, start
    return tuple(cases), understood


def _blocks(source: str):
    """Each test declaration, with the source between its braces."""
    seen: set[str] = set()
    for match in _TEST_DECL.finditer(source):
        name = (
            match.group("name") or match.group("jname")
            or (match.group("kname") or "").strip("`") or match.group("gname") or ""
        )
        if not name:
            continue
        unique = name if name not in seen else f"{name}#{len(seen)}"
        seen.add(unique)
        body = _braced(source, match.end())
        if body is None:
            continue
        yield unique, match.end(), body, source.count("\n", 0, match.start()) + 1


def _braced(source: str, start: int) -> str | None:
    """Text inside the next balanced ``{...}``. None when it does not close.

    Counting braces is not parsing: a brace inside a string literal miscounts.
    That produces a body that is too long or too short, so the failure is a
    missed or spurious *assertion*, never a crash — and the caller's timidity
    turns that into silence rather than a claim.
    """
    opened = source.find("{", start)
    if opened == -1 or opened - start > 400:
        return None
    depth = 0
    for index in range(opened, min(len(source), opened + 200_000)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[opened + 1:index]
    return None


def _assertions(body: str, base_line: int):
    """Every assertion shape recognised inside one test body."""
    for match in _FLUENT.finditer(body):
        subject = _clean(match.group("subject"))
        if subject is None:
            continue
        relation = _chain_relation(match.group("chain"))
        if relation is None:
            continue
        yield Assertion(
            subject=subject, relation=relation,
            line=base_line + body.count("\n", 0, match.start()),
            raw=_snippet(match.group(0)),
        )

    for match in _CALL.finditer(body):
        found = _from_call(match, body, base_line)
        if found is not None:
            yield found


def _chain_relation(chain: str) -> Relation | None:
    """Fold a ``.not.toBe(...)`` chain into one relation.

    Connectors such as ``to`` and ``be`` carry no meaning alone and are joined
    to the next link, which is how ``to.equal`` and ``toEqual`` end up as the
    same entry in one table.
    """
    links = [fold(link) for link in re.findall(r"\.\s*(\w+)", chain)]
    negated = any(link in NEGATIONS for link in links)
    for index, link in enumerate(links):
        for candidate in (link, link + (links[index + 1] if index + 1 < len(links) else "")):
            relation = FLUENT_RELATIONS.get(candidate)
            if relation is not None:
                if negated and relation is Relation.EQ:
                    return Relation.COMPARISON
                return relation
    return Relation.OPAQUE if links else None


def _from_call(match, body: str, base_line: int) -> Assertion | None:
    """``assertEquals(expected, actual)`` and friends."""
    name = match.group("name")
    relation = METHOD_RELATIONS.get(name) or FLUENT_RELATIONS.get(fold(name))
    if relation is None:
        return None
    subject = _clean(_last_argument(match.group("args")))
    if subject is None:
        return None
    return Assertion(
        subject=subject, relation=relation,
        line=base_line + body.count("\n", 0, match.start()),
        raw=_snippet(match.group(0)),
    )


def _last_argument(args: str) -> str:
    """The subject of an ``assertEquals``-style call.

    JUnit puts the expected value first and the actual second; testify puts the
    test handle first. Taking the last argument is right for both, and for a
    single-argument ``assertTrue``.
    """
    depth = 0
    parts = [""]
    for char in args:
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        if char == "," and depth == 0:
            parts.append("")
            continue
        parts[-1] += char
    return parts[-1].strip()


def _clean(text: str | None) -> str | None:
    """A subject worth comparing, or None when it is not one."""
    if not text:
        return None
    subject = " ".join(text.split())
    if not subject or len(subject) > _MAX_SUBJECT:
        return None
    if subject[0] in "\"'`" or subject.replace(".", "").isdigit():
        return None  # a literal is a value, not a subject
    return subject


def _snippet(text: str) -> str:
    return " ".join(text.split())[:160]


def _shape(body: str) -> str:
    """Structure-only fingerprint, for pairing a renamed test."""
    return "|".join(sorted(re.findall(r"\b(?:if|for|while|expect|assert\w*)\b", body)))


__all__ = ["extract", "reads", "SUFFIXES"]
