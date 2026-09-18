"""The curated adapter catalogue.

Adding a tool is a data change, not a code change. Every entry here is reviewed:
a project may enable any of these by name, and may not introduce one of its own,
because an adapter is a command this process will execute.

Costs matter. ``FAST`` tools are safe inside a pre-write hook; ``SLOW`` ones
invoke a build system and belong in CI or a pre-commit run, so the hook skips
them by default.
"""

from __future__ import annotations

from .adapter import FAST, SLOW, Adapter

_ADAPTERS: tuple[Adapter, ...] = (
    # ---------------------------------------------------------------- python
    Adapter("ruff", "Ruff lint rules", (".py", ".pyi"),
            ("ruff", "check", "--output-format", "json", "--force-exclude", "{path}"),
            "ruff_json", FAST, ("ruff", "--version"), "ruff check --fix", (0, 1)),
    Adapter("ruff-format", "Ruff formatting", (".py", ".pyi"),
            ("ruff", "format", "--check", "--quiet", "{path}"),
            "presence", FAST, ("ruff", "--version"), "ruff format", (0,)),
    Adapter("black", "Black formatting", (".py", ".pyi"),
            ("black", "--check", "--quiet", "{path}"),
            "presence", FAST, ("black", "--version"), "black .", (0,)),
    Adapter("isort", "Import ordering", (".py",),
            ("isort", "--check-only", "--quiet", "{path}"),
            "presence", FAST, ("isort", "--version"), "isort .", (0,)),
    Adapter("mypy", "Static types", (".py", ".pyi"),
            ("mypy", "--no-error-summary", "--no-color-output", "{path}"),
            "gnu", SLOW, ("mypy", "--version"), "", (0,)),
    Adapter("flake8", "Flake8 lint rules", (".py",),
            ("flake8", "{path}"), "gnu", FAST, ("flake8", "--version"), "", (0,)),
    Adapter("bandit", "Python security lint", (".py",),
            ("bandit", "-f", "sarif", "-q", "{path}"),
            "sarif", FAST, ("bandit", "--version"), "", (0, 1)),

    # ------------------------------------------------------------------ java
    Adapter("spotless", "Spotless formatting (Gradle)", (".java", ".kt", ".groovy"),
            ("gradle", "--quiet", "--offline", "spotlessCheck"),
            "presence", SLOW, ("gradle", "--version"), "gradle spotlessApply", (0,)),
    Adapter("spotless-maven", "Spotless formatting (Maven)", (".java", ".kt"),
            ("mvn", "-q", "-o", "spotless:check"),
            "presence", SLOW, ("mvn", "--version"), "mvn spotless:apply", (0,)),
    Adapter("google-java-format", "Google Java Format", (".java",),
            ("google-java-format", "--dry-run", "--set-exit-if-changed", "{path}"),
            "presence", FAST, ("google-java-format", "--version"),
            "google-java-format -i", (0,)),
    Adapter("checkstyle", "Checkstyle rules", (".java",),
            ("checkstyle", "-f", "sarif", "{path}"),
            "sarif", SLOW, ("checkstyle", "--version"), "", (0,)),
    Adapter("pmd", "PMD static analysis", (".java",),
            ("pmd", "check", "-f", "sarif", "-d", "{path}"),
            "sarif", SLOW, ("pmd", "--version"), "", (0, 4)),

    # ----------------------------------------------------------- javascript
    Adapter("eslint", "ESLint rules", (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"),
            ("eslint", "--format", "json", "{path}"),
            "gnu", FAST, ("eslint", "--version"), "eslint --fix", (0, 1)),
    Adapter("prettier", "Prettier formatting",
            (".js", ".jsx", ".ts", ".tsx", ".json", ".css", ".scss", ".md", ".yaml", ".yml"),
            ("prettier", "--check", "{path}"),
            "presence", FAST, ("prettier", "--version"), "prettier --write", (0,)),
    Adapter("biome", "Biome lint and format",
            (".js", ".jsx", ".ts", ".tsx", ".json"),
            ("biome", "check", "{path}"),
            "gnu", FAST, ("biome", "--version"), "biome check --write", (0,)),
    Adapter("tsc", "TypeScript type check", (".ts", ".tsx"),
            ("tsc", "--noEmit", "--pretty", "false"),
            "gnu", SLOW, ("tsc", "--version"), "", (0,)),

    # -------------------------------------------------------------------- go
    Adapter("gofmt", "Go formatting", (".go",),
            ("gofmt", "-l", "{path}"), "presence", FAST, ("gofmt", "-h"), "gofmt -w", (0,)),
    Adapter("go-vet", "Go vet", (".go",),
            ("go", "vet", "{path}"), "gnu", SLOW, ("go", "version"), "", (0,)),
    Adapter("golangci-lint", "golangci-lint", (".go",),
            ("golangci-lint", "run", "--out-format", "json", "{path}"),
            "gnu", SLOW, ("golangci-lint", "--version"), "", (0, 1)),

    # ------------------------------------------------------------------ rust
    Adapter("rustfmt", "Rust formatting", (".rs",),
            ("rustfmt", "--check", "--edition", "2021", "{path}"),
            "presence", FAST, ("rustfmt", "--version"), "cargo fmt", (0,)),
    Adapter("clippy", "Clippy lints", (".rs",),
            ("cargo", "clippy", "--quiet", "--message-format", "short"),
            "gnu", SLOW, ("cargo", "--version"), "cargo clippy --fix", (0,)),

    # ----------------------------------------------------------------- other
    Adapter("shellcheck", "Shell script lint", (".sh", ".bash"),
            ("shellcheck", "-f", "json", "{path}"),
            "gnu", FAST, ("shellcheck", "--version"), "", (0, 1)),
    Adapter("sqlfluff", "SQL lint", (".sql",),
            ("sqlfluff", "lint", "--format", "json", "{path}"),
            "gnu", SLOW, ("sqlfluff", "--version"), "sqlfluff fix", (0, 1)),
    Adapter("yamllint", "YAML lint", (".yaml", ".yml"),
            ("yamllint", "-f", "parsable", "{path}"),
            "gnu", FAST, ("yamllint", "--version"), "", (0,)),
)

BY_NAME = {adapter.name: adapter for adapter in _ADAPTERS}


def get(name: str) -> Adapter | None:
    return BY_NAME.get(name)


def names() -> tuple[str, ...]:
    return tuple(sorted(BY_NAME))


def for_path(path: str, names_wanted) -> tuple[Adapter, ...]:
    """Enabled adapters, in catalogue order, that apply to ``path``."""
    wanted = set(names_wanted)
    return tuple(a for a in _ADAPTERS if a.name in wanted and a.handles(path))
