"""Reading a policy document into the policy model.

Split from policy.py so that the model (what a rule *is*) and the reader (how a
JSON document becomes one) change independently — and so neither file outgrows
the 300-line limit in RULES.md section 1.

Malformed configuration degrades with a warning rather than raising: a policy
file that a newer Yieldpoint wrote, or that someone typo'd, must not stop an agent
from working.
"""

from __future__ import annotations

from typing import Any

from .policyfields import (
    _custom_rules, _fraction, _int, _linters, _positive, _routing,
    routing_sections,
    _section, _status, _str_tuple, _structure, _zones,
)
from .policy import (
    Metrics,
    Routing,
    DEFAULT_IGNORE,
    DEFAULT_PROTECTED_PATTERNS,
    Boundaries,
    ContinuousIntegration,
    CustomRule,
    GeneratedCode,
    Linters,
    LoopBreaker,
    Policy,
    Refactor,
    Scan,
    Structure,
    Subjects,
    TestContract,
    Voice,
    Zone,
)
from .verdict import Status


#: Every section the reader understands. A key outside this set is a typo or a
#: name someone reasonably guessed, and either way the setting they wrote is not
#: in force. Silence there is worse than a wrong value: they believe they
#: configured something, and the defaults quietly apply instead.
KNOWN_SECTIONS = frozenset({
    "version", "project", "test_contract", "boundaries", "loop_breaker",
    "linters", "metrics", "routing", "voice", "generated", "subjects",
    "refactor", "structure", "ci", "scan", "routing_session",
})


def _unknown_keys(raw: dict[str, Any], warnings: list[str]) -> None:
    for key in sorted(raw):
        if key in KNOWN_SECTIONS or key.startswith("_"):
            continue
        suggestion = _closest(key)
        hint = f"; did you mean {suggestion!r}?" if suggestion else ""
        warnings.append(
            f"unknown configuration key {key!r} — it is being ignored{hint}"
        )


def _closest(key: str) -> str | None:
    """The known section a mistyped key most resembles, if any is close."""
    import difflib

    matches = difflib.get_close_matches(key, sorted(KNOWN_SECTIONS), n=1, cutoff=0.6)
    return matches[0] if matches else None


def _metrics(section: dict, warnings: list[str]) -> Metrics:
    """Local accounting. Deliberately cannot name a command.

    A ``sink`` key here is ignored and reported. It is not a typo to correct
    quietly: a committed file that could name an executable would run it on
    every machine that cloned the repository, which SECURITY.md names as a
    vulnerability rather than a feature.
    """
    if "sink" in section:
        warnings.append(
            "metrics.sink in .yieldpoint.json is ignored — configuration may "
            "never name a command. Set the YIELDPOINT_SINK environment "
            "variable instead; see SECURITY.md.")
    try:
        import math
        price = float(section.get("price_per_million") or 0.0)
        if not math.isfinite(price):
            raise ValueError("non-finite price")
    except (TypeError, ValueError):
        warnings.append("metrics.price_per_million is not a number; no cost is shown")
        price = 0.0
    return Metrics(
        enabled=bool(section.get("enabled", True)),
        path=str(section.get("path") or Metrics.path),
        price_per_million=max(0.0, price),
        tokenizer=_tokenizer(section.get("tokenizer"), warnings),
        retain_omitted=bool(section.get("retain_omitted", False)),
    )


def _tokenizer(value: object, warnings: list[str]) -> str:
    """A named counter from the allowlist, or nothing.

    A misspelt name is reported rather than ignored. Silently falling back to
    estimates would leave a repository believing it was measuring.
    """
    from .. import tokenizer as counters

    if not value:
        return ""
    spec = str(value).strip()
    provider = spec.partition(":")[0].lower()
    if provider in counters.PROVIDERS:
        return spec
    known = ", ".join(sorted(counters.PROVIDERS))
    warnings.append(f"metrics.tokenizer '{spec}' names no known provider "
                    f"({known}); token counts stay estimates")
    return ""


def _refactor(raw: dict, warnings: list) -> Refactor:
    """Rules that parse cleanly and fail only when the path runs."""
    return Refactor(**{
        name: _status(raw.get(name), Status.REPAIR, warnings, f"refactor.{name}")
        for name in ("dangling_reference", "export_removed", "swallowed_exception")
    })


def read(raw: dict[str, Any], *, source_name: str = "<dict>") -> Policy:
    """Normalise a parsed `.yieldpoint.json` document into a :class:`Policy`."""
    warnings: list[str] = []
    project = _section(raw, "project", warnings)
    contract = _section(raw, "test_contract", warnings)
    boundaries = _section(raw, "boundaries", warnings)
    breaker = _section(raw, "loop_breaker", warnings)
    linters = _section(raw, "linters", warnings)
    metrics = _section(raw, "metrics", warnings)
    voice = _section(raw, "voice", warnings)
    generated = _section(raw, "generated", warnings)
    subjects = _section(raw, "subjects", warnings)
    refactor = _section(raw, "refactor", warnings)
    structure = _section(raw, "structure", warnings)
    ci = _section(raw, "ci", warnings)
    scanning = _section(raw, "scan", warnings)
    _unknown_keys(raw, warnings)

    patterns = _str_tuple(contract.get("protected_patterns"), warnings, "protected_patterns")

    return Policy(
        version=str(raw.get("version", "1.0")),
        project_name=str(project.get("name", "unnamed")),
        languages=_str_tuple(project.get("languages"), warnings, "languages") or ("python",),
        test_contract=TestContract(
            protected_patterns=patterns or DEFAULT_PROTECTED_PATTERNS,
            assertion_monotonicity=_status(
                contract.get("assertion_monotonicity"), Status.REPAIR, warnings,
                "assertion_monotonicity"),
            forbid_vacuous_assertions=_status(
                contract.get("forbid_vacuous_assertions"), Status.REPAIR, warnings,
                "forbid_vacuous_assertions"),
            forbid_new_skip_markers=_status(
                contract.get("forbid_new_skip_markers"), Status.REPAIR, warnings,
                "forbid_new_skip_markers"),
            forbid_swallowed_exceptions=_status(
                contract.get("forbid_swallowed_exceptions"), Status.REPAIR, warnings,
                "forbid_swallowed_exceptions"),
        ),
        ci=ContinuousIntegration(
            check_removed=_status(
                ci.get("check_removed"), Status.REPAIR, warnings, "ci.check_removed"),
            check_disabled=_status(
                ci.get("check_disabled"), Status.REPAIR, warnings, "ci.check_disabled"),
            paths=_str_tuple(ci.get("paths"), warnings, "ci.paths")
            or ContinuousIntegration().paths,
        ),
        structure=_structure(structure, warnings),
        scan=Scan(
            ignore=_str_tuple(scanning.get("ignore"), warnings, "scan.ignore") or DEFAULT_IGNORE,
            max_file_bytes=_int(
                scanning.get("max_file_bytes"), 1_000_000, warnings, "scan.max_file_bytes"),
        ),
        refactor=_refactor(refactor, warnings),
        subjects=Subjects(
            accessor_equivalence=bool(subjects.get("accessor_equivalence", True)),
        ),
        boundaries=Boundaries(
            on_violation=_status(
                boundaries.get("on_violation"), Status.REPAIR, warnings, "on_violation"),
            zones=_zones(boundaries.get("zones"), warnings),
        ),
        loop_breaker=LoopBreaker(
            window=_int(breaker.get("window"), 6, warnings, "window"),
            max_repeats_without_progress=_int(
                breaker.get("max_repeats_without_progress"), 3, warnings,
                "max_repeats_without_progress"),
            on_trip=_status(breaker.get("on_trip"), Status.ESCALATE, warnings, "on_trip"),
        ),
        linters=_linters(linters, warnings),
        **routing_sections(raw, warnings),
        metrics=_metrics(metrics, warnings),
        voice=Voice(
            severity_floor=_status(
                voice.get("severity_floor"), Status.ESCALATE, warnings, "voice.severity_floor"),
            max_spoken_findings=_int(
                voice.get("max_spoken_findings"), 3, warnings, "voice.max_spoken_findings"),
            confirm_on_removals=_int(
                voice.get("confirm_on_removals"), 2, warnings, "voice.confirm_on_removals"),
        ),
        generated=GeneratedCode(
            detect=bool(generated.get("detect", True)),
            on_hand_edit=_status(
                generated.get("on_hand_edit"), Status.REPAIR, warnings,
                "generated.on_hand_edit"),
            extra_patterns=_str_tuple(
                generated.get("extra_patterns"), warnings, "generated.extra_patterns"),
        ),
        source=source_name,
        warnings=tuple(warnings),
    )
