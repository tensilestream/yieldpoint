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
JavaScript and TypeScript; JUnit and AssertJ in Java and Kotlin; testify in
Go, and Go's own guard idiom, which has no assertion API at all.
The relation tables are shared with the Python path (spellings.py), so a
framework added there is understood here too.
"""

from __future__ import annotations

import re

from .recognise import Assertion
from .relation import Relation
from .testpatterns import (
    CALL, ELIXIR_ASSERT, ELIXIR_RELATIONS, FLUENT, GO_GUARD, GO_INVERSE,
    MAX_SUBJECT, NAME_GROUPS, RUBY_CALL, RUBY_OPENERS, SUBJECT_FIRST,
    CONSTANT_SUBJECTS, SKIP_MARKERS, SUFFIXES, TEST_DECL,
)
from .spellings import FLUENT_RELATIONS, METHOD_RELATIONS, NEGATIONS, fold

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
        assertions = tuple(_assertions(body, line, filename))
        # A body with nothing in it is *recognised*, not unrecognised. Timidity
        # exists so a file written in an assertion style this build cannot read
        # is never accused of being empty — but an empty body is unambiguous in
        # every language, and treating it as "not understood" meant `empty_test`
        # reached Python and nowhere else.
        understood = understood or bool(assertions) or not body.strip()
        cases.append(TestCase(
            qualname=name,
            line=line,
            assertions=assertions,
            is_empty=not body.strip(),
            body_hash=_shape(body),
            skip_markers=_skips(source, match_start=start, body=body),
        ))
    del start
    return tuple(cases), understood


def _declared_name(match) -> str:
    """The test's name, whichever language declared it."""
    for group in NAME_GROUPS:
        found = match.group(group)
        if found:
            return found.strip("`")
    return ""


def _body_of(source: str, match):
    """Ruby and Elixir close a block with ``end``; the rest use braces."""
    if match.group("rbname") or match.group("exname"):
        return _ended(source, match.end())
    return _braced(source, match.end())


def _blocks(source: str):
    """Each test declaration, with the source of its body."""
    seen: set[str] = set()
    for match in TEST_DECL.finditer(source):
        name = _declared_name(match)
        if not name:
            continue
        unique = name if name not in seen else f"{name}#{len(seen)}"
        seen.add(unique)
        body = _body_of(source, match)
        if body is None:
            continue
        yield unique, match.end(), body, source.count("\n", 0, match.start()) + 1


def _ended(source: str, start: int) -> str | None:
    """A Ruby body: from here to its matching ``end``.

    Depth counting, not parsing. An ``end`` inside a string literal miscounts,
    which yields a body that is too long or too short — so the failure is a
    missed or spurious assertion, never a crash, and the caller's timidity
    turns that into silence.
    """
    depth = 1
    collected: list[str] = []
    for line in source[start:].splitlines(keepends=True):
        stripped = line.strip()
        if stripped == "end" or stripped.startswith("end "):
            depth -= 1
            if depth == 0:
                return "".join(collected)
        elif stripped.startswith(RUBY_OPENERS) or stripped.endswith(" do"):
            depth += 1
        collected.append(line)
    return None


def _skips(source: str, *, match_start: int, body: str) -> tuple[str, ...]:
    """Skip markers on or inside this test.

    Annotations sit *above* the declaration, so a short window before it is
    searched as well as the body. Bounded deliberately: reading further up
    would attribute the previous test's marker to this one.
    """
    window = source[max(0, match_start - 160):match_start] + body
    return tuple(sorted({
        match.group(0) for pattern in SKIP_MARKERS
        for match in pattern.finditer(window)
    }))


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


def _assertions(body: str, base_line: int, filename: str = ""):
    """Every assertion shape recognised inside one test body."""
    yield from _fluent_assertions(body, base_line)
    yield from _call_assertions(body, base_line, filename)
    yield from _guard_assertions(body, base_line)
    if filename.endswith((".ex", ".exs")):
        yield from _elixir_assertions(body, base_line)


def _fluent_assertions(body: str, base_line: int):
    """``expect(x).toBe(1)``, ``assertThat(x).isEqualTo(1)``."""
    for match in FLUENT.finditer(body):
        subject = _clean(match.group("subject"))
        if subject is None:
            continue
        relation = _chain_relation(match.group("chain"))
        if relation is None:
            continue
        yield Assertion(
            subject=subject, relation=_relation_for(subject, relation),
            line=base_line + body.count("\n", 0, match.start()),
            raw=_snippet(match.group(0)),
        )


def _call_assertions(body: str, base_line: int, filename: str):
    """``assertEquals(a, b)``, ``assert_eq!(a, b)``, and Ruby's paren-less form."""
    patterns = [CALL]
    if filename.endswith(".rb"):
        patterns.append(RUBY_CALL)
    for pattern in patterns:
        for match in pattern.finditer(body):
            found = _from_call(match, body, base_line)
            if found is not None:
                yield found


def _elixir_assertions(body: str, base_line: int):
    """``assert total == 42``: a macro, no parentheses, operator carries strength."""
    for match in ELIXIR_ASSERT.finditer(body):
        expression = match.group("expr").strip()
        line = base_line + body.count("\n", 0, match.start())
        relation, subject = Relation.TRUTHY, expression

        for operator, found in ELIXIR_RELATIONS.items():
            left, separator, _right = expression.partition(operator)
            if separator and left.strip():
                relation, subject = found, left
                break

        cleaned = _clean(subject)
        if cleaned is None:
            continue
        yield Assertion(subject=cleaned,
                        relation=_relation_for(cleaned, relation), line=line,
                        raw=_snippet(match.group(0)))


def _guard_assertions(body: str, base_line: int):
    """Go's ``if <cond> { t.Fatal(...) }``, which is an assertion inverted."""
    for match in GO_GUARD.finditer(body):
        found = _from_go_guard(match, body, base_line)
        if found is not None:
            yield found



def _from_go_guard(match, body: str, base_line: int):
    """An ``if <cond> { t.Fatal(...) }`` guard, read as the assertion it makes.

    ``if err != nil`` is the one shape deliberately ignored: it is Go's error
    propagation idiom, present in nearly every test, and reading it as an
    assertion about ``err`` would bury the real ones in noise.
    """
    condition = match.group("cond").strip()
    if not condition or _is_error_check(condition):
        return None

    line = base_line + body.count("\n", 0, match.start())
    if condition.startswith("!"):
        subject = _clean(condition[1:])
        if subject is None:
            return None
        return Assertion(subject=subject,
                         relation=_relation_for(subject, Relation.TRUTHY),
                         line=line,
                         raw=_snippet(match.group(0)))

    for operator, relation in GO_INVERSE.items():
        left, sep, right = condition.partition(f" {operator} ")
        if not sep:
            continue
        subject = _clean(left)
        if subject is None:
            return None
        return Assertion(subject=subject,
                         relation=_relation_for(subject, relation), line=line,
                         expected=_clean(right), raw=_snippet(match.group(0)))
    return None


def _is_error_check(condition: str) -> bool:
    """``if err != nil`` and friends: plumbing, not verification."""
    stripped = condition.replace(" ", "")
    return stripped.endswith(("!=nil", "==nil")) and "err" in stripped.lower()


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


def _subject_of(name: str, args: str) -> str | None:
    """The argument naming what is under test, by the family's convention."""
    if name.startswith(SUBJECT_FIRST):
        first, _, _ = args.partition(",")
        return _clean(first) or _clean(_last_argument(args))
    return _clean(_last_argument(args))


def _from_call(match, body: str, base_line: int) -> Assertion | None:
    """``assertEquals(expected, actual)`` and friends."""
    name = match.group("name")
    relation = METHOD_RELATIONS.get(name) or FLUENT_RELATIONS.get(fold(name))
    if relation is None:
        return None
    subject = _subject_of(name, match.group("args"))
    if subject is None:
        return None
    return Assertion(
        subject=subject, relation=_relation_for(subject, relation),
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


def _relation_for(subject: str, relation: Relation) -> Relation:
    """A constant subject makes any relation vacuous.

    ``expect(true).toBe(true)`` reads as an equality until you notice nothing
    about the code under test appears in it.
    """
    return Relation.VACUOUS if subject in CONSTANT_SUBJECTS else relation


def _clean(text: str | None) -> str | None:
    """A subject worth comparing, or None when it is not one."""
    if not text:
        return None
    subject = " ".join(text.split())
    if not subject or len(subject) > MAX_SUBJECT:
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
