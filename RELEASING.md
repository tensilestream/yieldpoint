# Releasing

Every step is a command you run. Nothing here is automated on your behalf — commits, tags
and publishes are yours.

## 0. The name, and why it is this one

The project was called AegisFlow, then briefly Tensile. **`tensile` is taken on PyPI** by
DataRobot — actively maintained, in the same problem space (AI agent reliability), and it
installs a `tensile` command. Two packages competing for one name on `PATH` is a problem
no amount of documentation fixes.

`yieldpoint` was free, and is the better name anyway: the fracture is obvious — a failing
build announces itself — while the yield point, where a material stops springing back, is
the one that passes unnoticed. That is exactly what this finds.

**Check the name before any rename.** `https://pypi.org/pypi/<name>/json` returns 404 when
a name is free. Check the console script too, not only the package: they are separate
namespaces, and the command is what collides.

## 1. Pre-flight

```sh
./scripts/release-check.sh
```

It must print `RELEASE CHECK PASSED`. It runs the full suite, builds both artifacts,
installs the wheel into a throwaway virtualenv and exercises the CLI there — a clean-room
check, because `pip install -e .` can hide a packaging mistake that a real user would hit.

It also runs Yieldpoint against its own source. The correctness rules must be clean; the
maintainability findings are advisory and listed for information.

## 2. Version and changelog

Version lives in exactly two places and they must agree:

- `pyproject.toml` → `version`
- `yieldpoint/__init__.py` → `__version__`

`scripts/release-check.sh` fails if they drift.

Move the `[Unreleased]` entries in `CHANGELOG.md` under a new heading with today's date,
and add the comparison links at the bottom.

**If the verdict JSON changed shape, bump `SCHEMA_VERSION` in `yieldpoint/core/verdict.py`.**
It is versioned separately from the package because it is the cross-language API: a binding
written against schema 1 must not silently receive schema 2.

## 3. Commit and tag

```sh
git add -A
git commit -m "Release 0.1.0"
git tag -a v0.1.0 -m "Yieldpoint 0.1.0"
git push origin main --follow-tags
```

Tags are `vMAJOR.MINOR.PATCH`, annotated (`-a`) rather than lightweight so the tag carries
an author and date.

## 4. Publish

```sh
rm -rf dist build
python -m build
python -m twine check dist/*
python -m twine upload --repository testpypi dist/*    # rehearse first
python -m twine upload dist/*
```

Rehearsing on TestPyPI is not optional ceremony: **a version can never be re-uploaded to
PyPI**, even after deleting it. A bad `0.1.0` is spent, and the next attempt has to be
`0.1.1` with no explanation for the gap.

Uploading needs an API token from <https://pypi.org/manage/account/token/>, either in
`~/.pypirc` or as `TWINE_USERNAME=__token__` and `TWINE_PASSWORD=pypi-...`. Scope the
first token to "entire account" — a project-scoped token cannot create a project that
does not exist yet — then replace it with a project-scoped one after the first release.

Verify the published artifact rather than trusting the upload:

```sh
python -m venv /tmp/verify && /tmp/verify/bin/pip install yieldpoint==0.1.0
/tmp/verify/bin/yieldpoint --version
/tmp/verify/bin/yp --version          # the short alias must resolve too
```

## 5. After

Open a GitHub release against the tag, pasting that version's changelog section.

## Versioning rules

- **Patch** — a bug fix, or a rule that now catches something it should always have caught.
- **Minor** — a new rule, a new surface, or a new configuration key with a default that
  preserves existing behaviour.
- **Major** — a default that changes what an existing project's verdict is, a removed
  configuration key, or a `SCHEMA_VERSION` bump.

A new rule enabled by default changes verdicts for existing users. Ship such a rule at
`repair` severity, never `block`, so an upgrade cannot start failing someone's pipeline
overnight.
