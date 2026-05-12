# Contributing to BioSlice5X

## For wet-lab collaborators (no Python experience required)

BioSlice5X is designed to be useful to scientists who don't write code.
Two paths to contribute meaningful work without touching Python:

**1. Calibrate a bioink against your own viability data.** Pick a bioink
in `src/bioslice5x/bioink/library/` — every record carries a
`calibrated_against: "uncalibrated, literature default"` field. Run the
shear-viability assay on your specific lot/cell-line, replace the value
with your measurement, and update the `calibrated_against:` string with
a citation form: `"Your lab name, YYYY-MM-DD, cell type at density,
assay type, n=N"`. The G-code header surfaces this provenance on every
emitted file. Open a PR with the updated YAML — no Python edits needed.

**2. Contribute a recipe.** A `samples/*.yaml` recipe captures one
specific print recipe (mesh + bioinks + slicing params + bath). New
recipes drop into `samples/`, optionally with a sample STL produced via
`samples/generate_samples.py`. The CHIPS pancreatic recipe is the
template — copy it and adapt.

**3. Report calibration drift.** If a shipped value doesn't match your
wet-lab measurements, open a GitHub issue with the assay protocol, the
measured value, and the source citation. We'd rather mark a value as
"contested, see issue #N" than ship a wrong default.

For all three, no Python knowledge is required. The Python contributors
listed below handle the code review and the CI gate.

## Python versions

**Runtime requirement: Python 3.11+.** `pyproject.toml` declares
`requires-python = ">=3.11"`. The G-code emitter uses `from datetime
import UTC`, which is 3.11+ only. CI runs on 3.11 and 3.12.

Older Pythons (e.g., 3.10) can import the package and run most submodules
(schemas, geometry, kinematics, validation) but **cannot run
`emit_rrf`** — calling `Slicer.slice()` raises a clear `RuntimeError` with
this same message. If you're stuck on 3.10 for sandbox reasons, all tests
that don't transitively call `emit_rrf` still run.

## Dev setup

```bash
uv sync --all-extras --dev
uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy
```

CI runs all four on every PR. Locally, run them before opening a PR.

## ADRs (Architecture Decision Records)

User-visible behavior decisions with ≥2 plausible alternatives that
produce visibly different print outcomes require an ADR in `docs/adr/`
before implementation. See [`docs/adr/README.md`](docs/adr/README.md) for
the threshold rule.

Cell-safety-implicated decisions: write the ADR draft, then ask for a
review before implementing. Routine ADRs without cell-safety implications
are authored and committed directly.

## Worked-example drift protection

Any docs (ADR, ARCHITECTURE.md, phase notes) containing numerical worked
examples must be pinned by a test that re-derives the numbers from the
code. Pattern: see `tests/test_phase_2b_notes_examples.py` and
`tests/test_adr_001_examples.py`.

## Golden file regenertion

Stable G-code output paths are locked by golden files in `tests/golden/`.
Intentional output changes regenerate via:

```bash
BIOSLICE5X_REGEN_GOLDEN=1 uv run pytest tests/test_*_golden.py
```

Review the diff against the previous golden carefully — every byte change
should correspond to an intentional code or schema change.

## Calibration provenance

Every empirically-tunable parameter (bioink rheology, cell-safety
thresholds, bath drag multipliers) carries a `calibrated_against` field.
The default is the literal string `"uncalibrated, literature default"`.
**Do not silently change a default value without updating the
`calibrated_against` field to name the source of the new number.** The
G-code header surfaces calibration status; downstream tools may refuse
to print uncalibrated files in regulated contexts.

## Project structure

- `src/bioslice5x/` — library code, src-layout.
- `tests/` — pytest tests. One file per concern; golden files in
  `tests/golden/`.
- `docs/` — long-form documentation, including ADRs in `docs/adr/`.
- `schemas/` — JSON Schema exports for recipe and profile (regenerated
  by `scripts/export_schemas.py`).
- `samples/` — small mesh files used in tutorials and tests.

## Module dependency rules

The architecture enforces module layering. Lower-layer modules must not
import higher-layer modules. From bottom up:

```
errors, kinematics/canonical, geometry/types, pathing/types, bioink/models
    ↓
bath/models, profile/models, recipe/models, geometry/mesh, geometry/flat_slicer,
geometry/conformal_slicer, kinematics/chain, kinematics/singularity
    ↓
extruder, pathing/perimeter, pathing/conformal_perimeter, pathing/infill,
recipe/orientation, postprocessor
    ↓
slicer, cli
```

Cross-module API at boundaries uses structural Protocols
(`Point3DLike`, `BathSurface`, `KinematicChain`, `OrientationProvider`)
where dependency direction would otherwise create a cycle. Don't paper
over a cycle with `if TYPE_CHECKING` — introduce a Protocol.

## When to update which docs

- ARCHITECTURE.md — only for structural changes (new modules, new
  dispatch points, new general-form decisions).
- PHASE_NN_NOTES.md — for phase-specific notes when starting or
  finishing a phase. Not for routine work within a phase.
- ADRs — for user-visible behavior decisions per the threshold rule.
- README.md — for user-facing changes that affect quickstart or
  supported workflows.
- CHANGELOG.md — every release.

## Patterns we don't violate (and what to do if you want to)

The codebase has established patterns. If you find yourself wanting to:

- Add a second dispatch point for an existing concept,
- Add a special-case code path for a "common" input,
- Import directly across module boundaries that should use a Protocol,
- Skip a worked-example test because "it's just a small example,"
- Silently change a `calibrated_against` value,
- Implement a user-visible decision without an ADR,

— stop and discuss. The pattern may be wrong, but the discussion is
the path to changing it, not a unilateral revision in the PR.
