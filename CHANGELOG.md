# CHANGELOG

All notable changes to BioSlice5X are recorded here.

## [0.1.0] — 2026-05-11

**Initial release.** Single-syringe and multi-syringe (kind=all
regions) flat and wrap-around-axis slicing produces valid
RepRapFirmware G-code for the Open5X Prusa and Voron profiles.

### Phase 1 — Architecture & scaffolding
- `ARCHITECTURE.md`, `docs/OPEN5X_NOTES.md`,
  `docs/BIOPRINTING_REQUIREMENTS.md`.
- src-layout, ruff + mypy strict + pytest in CI, MIT license, uv-based
  dependency management.
- Domain-specific error classes (`CellViabilityError`,
  `KinematicSingularityError`, etc.).

### Phase 2a — 3-axis baseline
- Pydantic v2 schemas: `Bioink`, `CellPayload`, `Recipe`,
  `MachineProfile` with `calibrated_against` provenance everywhere.
- 5 reference bioinks + 2 cell baselines + 1 hypothetical 3-axis
  profile.
- trimesh-backed flat horizontal slicer.
- Single-perimeter path generation.
- `DisplacementSyringe` + Newtonian wall-shear-stress + cell-viability
  validation that raises `CellViabilityError` on threshold violation.
- RRF G-code emitter with bioink metadata header.
- End-to-end cube → G-code library API.

### Phase 2b — A/C kinematics
- Canonical `(tilt_rad, swivel_rad)` kinematic math (letter-free).
- `KinematicChain` Protocol with `ThreeAxisKinematics` and
  `TiltSwivelKinematics` siblings.
- Smooth-through singularity handling at |tilt| < 2°.
- `TiltSwivelAxis.invert` flag for right-hand-rule commissioning fix.
- `open5x_prusa.yaml` (A+C, X tilt) and `open5x_voron.yaml` (B+C, Y tilt).
- VERIFY-AT-COMMISSIONING callout in OPEN5X notes.
- `docs/PHASE_2B_NOTES.md` worked examples doctest-locked.
- Sobol-grid forward/inverse kinematic round-trip (2048 × 6 configs).
- `;META: key=value` machine-readable G-code header block.
- `;========== WARNING: SAFETY_OVERRIDE ==========` banner with
  per-violation detail on force-override.
- `M104 S<temp> T<id>` syringe-temperature emission.
- Boundary-case `CellViabilityError` tests (at, just below, just above).

### Phase 2c / 2c.1 / 2c.2 — Conformal + bath + multi-mode
- `WrapAroundAxisSlicing` mode: `wrap_axis="z"` (swivel),
  `wrap_axis="x"` (Prusa tilt), `wrap_axis="y"` (Voron tilt).
- Configurable `conformal_arc_sampling_mm` per-bioink feature size.
- `bath/` module: `BathSurface` Protocol, `PlaneBath` model,
  `Point3DLike` structural typing to avoid circular imports.
- Bath calibration provenance (`calibrated_against` + `;META:`).
- `recipe/orientation.py` strategy dispatch: `FixedOrientation`,
  `PerLayerOrientation`.
- ADR-001: wrap-tilt clamping (refuse-loudly default + opt-in arc-split).
- ADR-002: default infill pattern (rectilinear with 90° layer
  alternation).
- `pathing/infill.py`: unified flat/conformal scan-line generator with
  pluggable lift function.
- `ClampingExceededError` raised when wrap-tilt arc exceeds profile
  range without `allow_tilt_arc_split`.
- Flat-mode golden file regression lock.

### Phase 2d — Multi-syringe
- Slicer accepts N syringes; tool-change `T<n>` emitted per
  syringe-id transition.
- Aggregated stress report with per-syringe entries.
- META block carries `syringe_count`.

### v0.1.0 release polish
- `CONTRIBUTING.md`, `LIMITATIONS.md`, `CHANGELOG.md`.
- JSON Schema export for Recipe and MachineProfile.
- `import-linter` contracts enforcing module layering.
- Sample mesh generator (`samples/`).
- Quickstart tutorial.

### Verification (CI)
- ruff check + ruff format clean across the codebase.
- mypy strict clean across all source files.
- pytest passing on Python 3.11 and 3.12.
- import-linter contracts enforced.
- JSON schemas regenerated and diffed.
- Worked-example tests pin every numerical doc.

## Future versions

See [`LIMITATIONS.md`](LIMITATIONS.md) for what v0.1.0 doesn't ship.
v0.1.1 targets bbox regions, per-bioink retract/purge, conformal-infill
wiring, and cross-region travel optimization. v0.2.0 targets Marlin
dialect, Rabinowitsch-Mooney shear corrections, pneumatic extrusion,
and the wet-lab-calibrated bath model.
