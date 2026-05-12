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

## [0.2.0] — Phase 4 & Phase 5: 3D toolpath viewer (in progress)

### Added

- `bioslice5x preview <gcode>` CLI subcommand opens a PyVista-backed
  3D viewer of the toolpath: extrusion moves colored by Z, travel moves
  as grey segments, tool-orientation arrows at sampled extrusion points,
  build-volume wireframe (when `--profile` is supplied).
- `ToolpathViewer` and `preview_gcode()` public API in
  `bioslice5x.visualization`.
- `parse_gcode()` reads BioSlice5X-emitted G-code into a list of
  `ParsedMove` records. Captures X/Y/Z + A/B/C rotary tokens + E volume
  + F feed + the full `;META:` and prose header. Useful for any
  downstream tool that needs to consume our G-code.
- "Preview toolpath" button in the Tkinter GUI launches the viewer on
  the just-sliced output. Runs in a background thread so the GUI stays
  responsive.
- ADR-004 documents the PyVista vs Three.js / matplotlib / Open3D
  decision and the worked-example behaviour.

### Changed

- `[project.optional-dependencies] viz` continues to gate the PyVista
  dep; users without it still get the parser (useful for headless
  scripts) and a clear RuntimeError pointing at `bioslice5x[viz]` when
  they try to render.

### Added — Phase 5: stress coloring, layer scrubbing, mesh overlay (ADR-005)

- **Per-segment wall-shear-stress coloring.** The RRF postprocessor now
  emits a `;STRESS:<Pa>` trailing comment on every extrusion G1 line.
  The viewer parses these into `ParsedMove.wall_shear_pa`. A new
  `color_by` parameter (`"z"` default, or `"shear"`) on `ToolpathViewer`
  and `preview_gcode()` switches the extrusion colormap from Z-height
  (viridis) to wall shear stress (hot). When the caller supplies the
  active cell-payload's threshold via `cell_stress_threshold_pa`, the
  colormap is clamped to `[0, threshold]` so red marks the
  cell-viability limit exactly. CLI flags: `--color-by`,
  `--stress-threshold-pa`.
- **Layer scrubbing.** PyVista slider widget controls how many layers
  of the print are visible. Layer indices are dual-mode: Z-banded for
  flat / wrap-Z prints, ordinal-banded (100 buckets over move order) as
  a fallback for conformal / 5-axis prints with continuously varying Z.
  The slider is disabled in headless screenshot mode.
- **Source-mesh overlay.** Optional STL/OBJ rendered semi-transparent
  behind the toolpath, for "what was asked vs what was sliced"
  comparison. Failure to load the mesh is non-fatal — the rest of the
  scene renders and the info overlay surfaces the load error. CLI flags:
  `--mesh <path>`, `--mesh-opacity <f>`.
- **GUI exposes the new viewer options.** The Tkinter "Preview toolpath"
  button now passes the active color mode, mesh-overlay toggle, and the
  most-restrictive cell-shear threshold captured from the last successful
  slice.
- **ADR-005** documents the Phase 5 viewer design decisions.

### Added — v0.1.1: bbox region selector, demo command, distribution polish

- **`Region(kind="bbox")` spatial selector.** Per-syringe axis-aligned
  bounding-box regions filter the slicer's layer geometry: layers outside
  the bbox's z-range are dropped whole; remaining layers' polygons are
  clipped against the XY rectangle with shapely. The CHIPS pancreatic
  reference recipe now uses bbox regions for the fibrin/MIN6 core
  (5x5x4 prism) and `kind: all` for the collagen shell — making the
  geometric partition correct end-to-end. The `Region` schema is a
  proper discriminated union (`RegionAll | RegionBBox`); a
  `submesh` kind is reserved for v0.2.x.
- **`bioslice5x demo` command.** Zero-config end-to-end run: generates
  a 10mm cube in memory, builds a single-syringe collagen recipe,
  slices on the always-shipped `hypothetical_3axis` profile, opens the
  viewer with shear coloring + mesh overlay. Flags: `--output-dir`,
  `--no-viewer`, `--screenshot` for CI / headless / sharing use cases.
  One-command first-run validation after `pip install`.
- **Distribution & sharing polish.**
  - `CITATION.cff` — Citation File Format for the project + the
    Lee 2019 *Science* FRESH paper + the Shiwarski 2025 *Science
    Advances* CHIPS paper + the Open5X HardwareX reference.
  - README CI / license / Python badges.
  - README screenshots: Z-colored toolpath, shear-colored CHIPS,
    mesh-overlay CHIPS (`docs/screenshots/`).
  - README "Install from source" section covering both `uv` and
    `pip install git+https://…`.
  - `CONTRIBUTING.md` "For wet-lab collaborators" — three paths to
    contribute without writing Python (calibrate a bioink, contribute
    a recipe, report calibration drift).
- **Layer-contract fix.** `pyproject.toml` import-linter contract had
  a pre-existing "shared descendants" structural conflict
  (`bioslice5x.recipe` parent listed at one layer while
  `bioslice5x.recipe.orientation` lived at another). Replaced the
  `bioslice5x.recipe` reference with explicit submodules to keep the
  layer intent without the structural overlap.

### Added — CHIPS reference & research integration

- `bioink/library/cells.yaml` gains `MIN6_beta_cell` — the pancreatic
  β-cell payload used in the CHIPS T1D reference geometry. Conservative
  1.5 kPa wall-shear threshold, calibrated_against cites Shiwarski et al.
  2025 Science Advances and the PMC9756521 cell-damage review.
- `samples/chips_pancreatic_recipe.yaml` — two-syringe (fibrin/MIN6 +
  collagen) reference recipe for the CHIPS T1D construct. Loud about
  the v0.1.x limitations (submesh region selector, perfusion-channel
  writing) it doesn't yet exercise.
- `samples/chips_pancreatic_envelope.stl` — centimeter-scale disc
  envelope mesh for the CHIPS reference recipe; generated by
  `samples/generate_samples.py`.
- `docs/BIOPRINTING_REQUIREMENTS.md` gains §1.1 (modality landscape:
  inkjet / extrusion / LIFT / SLA-DLP / volumetric — situates BioSlice5X
  in the wider field), §3.1 (bioink category taxonomy: natural /
  synthetic / ceramic), §6.1 (CHIPS pancreatic construct reference
  geometry spec), and §8.1 (FDA April 2025 NAM directive and the
  forthcoming `SliceResult.regulatory_report()` deliverable). Cites the
  Science 2019 FRESH paper, the Science Advances 2025 CHIPS paper, and
  the FluidForm Bio ADA 85 / IPITA 2025 communications.

## Future versions

See [`LIMITATIONS.md`](LIMITATIONS.md) for what v0.1.0 doesn't ship.
v0.1.1 targets bbox regions, per-bioink retract/purge, conformal-infill
wiring, and cross-region travel optimization. v0.2.0 targets Marlin
dialect, Rabinowitsch-Mooney shear corrections, pneumatic extrusion,
and the wet-lab-calibrated bath model.
