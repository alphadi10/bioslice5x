# Releasing BioSlice5X

This document is the maintainer runbook for cutting a release. The
distribution artifacts are produced by GitHub Actions; the maintainer
runs the manual steps below.

## Prerequisites (one-time)

1. **PyPI Trusted Publisher** — register `bioslice5x` on PyPI and add a
   Trusted Publisher pointing at this repo and the `release` workflow.
   No long-lived API token to manage.
2. **PyPI name reservation** — verify `bioslice5x` is available at
   <https://pypi.org/project/bioslice5x/>. If taken, register an
   alternative (e.g., `bioslice5x-slicer`) and update `pyproject.toml`
   `name` plus all references in README/CONTRIBUTING/CHANGELOG.
3. **GitHub repo set up** — `bioslice5x` org or user, with the
   `release.yml` workflow enabled.

## Cutting a release

### 1. Land all changes on `main`

- Every change passes the verification gate (ruff / mypy / pytest /
  import-linter / schema regen).
- `CHANGELOG.md` has an entry for the new version dated today.
- `pyproject.toml` `version` and `src/bioslice5x/__init__.py`
  `__version__` are bumped and match.

### 2. Verify CI is green on `main`

CI runs on every push:

- `ruff check`, `ruff format --check`
- `mypy --strict` across all source files
- `import-linter` contracts
- `pytest -v` on Python 3.11 and 3.12
- `scripts/export_schemas.py` regenerates schemas and `git diff
  --exit-code` confirms no drift

If anything is red, fix on `main` before tagging.

### 3. Build + test locally (smoke check)

```bash
uv build
# Inspect dist/ — should contain bioslice5x-<version>.tar.gz and
# bioslice5x-<version>-py3-none-any.whl.

# Install the wheel into a clean venv and run a full slice.
python -m venv /tmp/release-test
source /tmp/release-test/bin/activate
pip install dist/bioslice5x-<version>-py3-none-any.whl
bioslice5x --version
python samples/generate_samples.py
bioslice5x slice samples/cube_10mm.stl \
    --profile hypothetical_3axis \
    --recipe samples/cube_collagen_recipe.yaml \
    --output /tmp/release-test.gcode
head -50 /tmp/release-test.gcode
deactivate
```

If any step fails, do NOT tag. Fix on `main` and try again.

### 4. Tag and push

```bash
git tag -a v0.1.0 -m "v0.1.0 — initial release"
git push origin v0.1.0
```

The `release.yml` workflow triggers on the tag push and:

1. Builds sdist + wheel via `uv build`.
2. Uploads them to a draft GitHub Release for the tag.
3. Builds PyInstaller single-file binaries on `ubuntu-latest`,
   `macos-13` (x86_64), `macos-latest` (arm64), and `windows-latest`.
4. Smoke-tests each binary (`--version` + `slice --help`).
5. Uploads each renamed binary to the same GitHub Release.

### 5. Promote the GitHub Release

Once the workflow completes:

1. Open the draft release in the GitHub UI.
2. Verify all artifacts are attached: sdist, wheel, 4 binaries.
3. Paste the CHANGELOG entry for this version into the release notes.
4. Add a "Calibration disclaimer" footer (copy from README.md).
5. Click "Publish release."

### 6. Publish to PyPI

```bash
uv publish dist/*
```

This uses the configured Trusted Publisher and requires no token.

If the upload fails (PyPI name conflict, etc.), see "Failure modes"
below.

### 7. Announce

- Update README.md with the new install command if needed (the v0.1.0
  README already says `pip install bioslice5x`).
- Open a discussion or issue on the repo announcing the release.
- (Optional) Cross-post on relevant channels: bioprinting Slack/Discord
  communities, r/bioprinting, Feinberg-lab adjacent venues.

## macOS arm64 vs x86_64

v0.1.0 ships two separate macOS binaries (`macos-13` = x86_64,
`macos-latest` = arm64). `universal2` (single binary supporting both)
requires additional PyInstaller configuration and was not pursued for
v0.1.0 because the matrix-based approach is simpler and the maintenance
cost of dual binaries is small. Filed as a v0.1.1 polish task.

## Failure modes

### PyPI name conflict

If `bioslice5x` is taken on PyPI:

1. Pick an alternative name (`bioslice5x-slicer`, `bioslice-5x`, etc.).
2. Update `pyproject.toml` `name`, README install command, CHANGELOG.
3. Cut a `v0.1.0-rc1` tag first to verify the rename works end-to-end.
4. Re-tag as `v0.1.0` once verified.

### CI binary build fails on one OS

The `fail-fast: false` matrix means other OS builds still complete.
Investigate the failed OS, fix in a patch release (`v0.1.0.post1` or
`v0.1.1`), and re-trigger by tagging again.

### `uv publish` fails

If the Trusted Publisher isn't recognised, fall back to a one-time
manual upload with an API token:

```bash
uv publish --token <token> dist/*
```

Document the failure mode in a `docs/INCIDENTS/<date>.md` for future
reference.

## Post-release

1. Bump `pyproject.toml` and `__init__.py` to the next patch version
   with a `.dev0` suffix (e.g., `0.1.1.dev0`).
2. Open a tracking issue for the next release with the v0.1.1 / v0.2.0
   scope items from `LIMITATIONS.md`.
3. Update `CHANGELOG.md` with an empty `[Unreleased]` section above
   the just-shipped version.

## Why we don't auto-publish to PyPI on tag

A manual `uv publish` step gives the maintainer one last chance to
inspect the built artifacts (especially the PyInstaller binaries) before
the public install command starts pulling them. The GitHub Release is
authoritative; PyPI follows.
