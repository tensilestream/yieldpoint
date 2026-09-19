# Releasing

Commits and tags are yours to make. Publishing runs in CI once a tag is pushed; section 5
is the manual fallback.

## 0. Names are claimed, not chosen

Before introducing any new published name, check it is free.
`https://pypi.org/pypi/<name>/json` returns 404 when it is. Check the console script as
well as the package: they are separate namespaces, and the command on `PATH` is the one
that actually collides.

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

## 4. Publish (Automated via GitHub Actions)

Yieldpoint uses the same automated release pipeline as `buildanchor` (`.github/workflows/release.yml`).

### Option A: Manual Trigger via GitHub Actions (Recommended)
1. Go to **Actions** → **Release & Publish** → **Run workflow**.
2. Optionally specify a release tag (e.g. `v0.1.0`), or leave blank to use the version from `pyproject.toml`.
3. Choose whether to do a **Dry run** first to validate build and test steps without publishing.
4. When run, GitHub Actions:
   - Validates the test suite and runs `./scripts/release-check.sh`
   - Builds distribution archives (`.whl`, `.tar.gz`) and computes SHA-256 checksums
   - Creates an annotated Git tag and a GitHub Release with assets
   - Publishes to PyPI via Trusted Publishing (OIDC) or `PYPI_API_TOKEN` secret
   - Auto-bumps the patch version on `main` for the next dev cycle (`[skip ci]`)

### Option B: Push a Git Tag
```sh
git tag -a v0.1.0 -m "Yieldpoint 0.1.0"
git push origin v0.1.0
```
This triggers `.github/workflows/release.yml` automatically.

### Configuring PyPI Authentication & Secrets

In `https://github.com/tensilestream/yieldpoint/settings/secrets/actions`:

1. **PyPI Trusted Publishing (OIDC - Recommended & zero-secret)**:
   - PyPI supports OpenID Connect (OIDC) authentication directly from GitHub Actions without saving API tokens.
   - On PyPI ([pypi.org/manage/account/publishing/](https://pypi.org/manage/account/publishing/)):
     - **PyPI Project Name**: `yieldpoint`
     - **Owner**: `tensilestream`
     - **Repository name**: `yieldpoint`
     - **Workflow name**: `release.yml`
     - **Environment name**: `pypi`
   - The `pypi` environment is already configured on the GitHub repository.

2. **PyPI API Token (Alternative)**:
   - If using token authentication instead of OIDC, add repository secret:
     - Name: `PYPI_API_TOKEN`
     - Value: `pypi-...`

---

## 5. Manual CLI Publish (Fallback)

If publishing manually from a local machine instead of CI:

```sh
rm -rf dist build
python -m build
python -m twine check dist/*
python -m twine upload --repository testpypi dist/*    # rehearse first
python -m twine upload dist/*
```

Uploading needs an API token from <https://pypi.org/manage/account/token/>, either in
`~/.pypirc` or as `TWINE_USERNAME=__token__` and `TWINE_PASSWORD=pypi-...`.

Verify the published artifact rather than trusting the upload:

```sh
python -m venv /tmp/verify && /tmp/verify/bin/pip install yieldpoint==0.1.0
/tmp/verify/bin/yieldpoint --version
/tmp/verify/bin/yp --version          # the short alias must resolve too
```

## 6. After


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
