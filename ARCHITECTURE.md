# BioSlice5X — Architecture

**Status:** v0 — pre-implementation. Architecture for review, scaffolding only.
**Companion docs:** [`docs/OPEN5X_NOTES.md`](docs/OPEN5X_NOTES.md), [`docs/BIOPRINTING_REQUIREMENTS.md`](docs/BIOPRINTING_REQUIREMENTS.md).

This document defines the module layout, data flow, and the three load-bearing design decisions: how extrusion is modelled, how bioinks are described, and how cell viability is enforced. It is deliberately specific so review can be a yes/no on concrete choices rather than a hand-wave.

---

## 1. Goals & Non-Goals

**Goals (v1):**
- Take a closed manifold mesh (STL/OBJ) and an A+C 5-axis machine profile, produce RepRapFirmware G-code that drives a multi-syringe FRESH bioprinter.
- Support conformal slicing (curved layers along a surface) as a first-class mode, not a flag.
- Refuse to emit G-code that violates per-bioink cell-viability shear-stress limits; the refusal is loud and identifies the offending segment.
- Be extensible to pneumatic extrusion and A+B kinematics behind explicit interfaces, without implementing either in v1.

**Non-goals (v1):**
- Pneumatic/pressure-based extrusion (interface only; first implementation is displacement).
- A+B or other kinematic configurations (interface only; first implementation is A+C).
- Tree/grid support generation (FRESH bath provides omnidirectional support).
- Marlin G-code output (RRF dialect first; Marlin in a later phase).
- Cell-stress modelling beyond steady-state laminar pipe-flow (extensional/transient effects are warned-on but not modelled in v1).

---

## 2. Module Layout

Src-layout package: `src/bioslice5x/`. Each module name below corresponds to a directory with `__init__.py`. Public API is exposed at the package root; submodule contents are implementation detail.

```
src/bioslice5x/
├── geometry/         # mesh I/O, conformal slicing, curved-layer generation
├── kinematics/       # forward/inverse transforms, A+C transforms, singularity detection
├── pathing/          # toolpath generation, travel optimization, collision checks
├── extruder/         # Extruder protocol, displacement-syringe impl, multi-syringe coordinator
├── bioink/           # Bioink dataclasses, YAML loader, shear-stress + viability calc
├── postprocessor/    # G-code emitter (RRF dialect first)
├── visualization/    # 3D toolpath preview (deferred to phase 5; stub only in v1)
├── profile/          # Machine profile loader (axis limits, feed caps, build volume)
├── errors.py         # CellViabilityError, KinematicSingularityError, BathCollisionError, …
└── cli.py            # bioslice5x slice <mesh> --profile <profile.yaml> --recipe <recipe.yaml>
```

### Responsibilities, in plain terms

**`geometry`** — Read meshes. Compute conformal slices: given a target surface (the part) and a substrate surface (the curve we wrap deposition onto), produce ordered slice geometries that are *curved* in 3D, not constrained to z = const. v1 starts with a "wrap around an axis" mode (the simplest non-planar case) before tackling arbitrary curved layers. Coordinate frame here is the part frame, not the machine frame — `kinematics` does the transform.

**`kinematics`** — All angle/translation math. Defines `KinematicChain` as a Protocol; the v1 implementation is `ACKinematics(tilt_about=X, plate_about=Z, tilt_range_deg, plate_range_deg)`. Provides:
- `forward(part_pose) → machine_pose` for visualization and validation.
- `inverse(part_pose) → machine_pose` for path generation.
- `tool_orientation_per_point(path) → list[(machine_pose, joint_angles)]`.
- `detect_singularity(joint_angles) → SingularityKind | None` (gimbal-lock-like configurations).
- `replan_around_singularity(path)` — graceful handling.

A+B (or any other configuration) plugs in as a sibling implementation of `KinematicChain`. The path generator never knows which is in use.

**`pathing`** — Toolpath generation from sliced geometry. Travel-move optimization: needle paths through the bath should minimize crossings of already-deposited regions because the kerf disturbs prior deposition (per `BIOPRINTING_REQUIREMENTS.md` §4). Collision detection: needle vs. already-deposited geometry — warn or replan, but don't silently violate.

**`extruder`** — `Extruder` is a Protocol. v1 implements `DisplacementSyringe(inner_diameter_mm, total_volume_uL, current_plunger_mm, nozzle_gauge, temperature_setpoint_c, bioink)`. Provides:
- `volume_to_plunger_displacement(uL) → mm` — geometric, syringe-specific.
- `expected_flow_rate(feed_mm_per_min, line_cross_section_mm2) → uL_per_s` — from path width × layer height × feed.
- `compute_wall_shear_rate(flow_rate, needle) → 1/s` and `compute_wall_shear_stress(flow_rate, needle, bioink) → Pa` — Newtonian formula `τ = (4·Q)/(π·r³)` as the default; power-law / Herschel-Bulkley applied per the bioink's rheological fit (see §4 below).

`MultiSyringeCoordinator` owns the set of extruders, handles tool-change G-code, per-syringe retract profiles, priming sequences. CHIPS uses up to ~3–4 materials per print (per `BIOPRINTING_REQUIREMENTS.md` §6), so the coordinator's data model does not hard-cap.

**`bioink`** — `Bioink` and `CellPayload` dataclasses (see §4). YAML loader at `bioslice5x.bioink.library` reads files from `src/bioslice5x/bioink/library/*.yaml`; users add bioinks by dropping YAML files there. Validation is at load time. Shipping defaults: collagen-I, fibrin, alginate, GelMA, dECM, plus a small `cell_lines.yaml` with conservative shear-stress limits for common cell types.

**`postprocessor`** — Takes the path (now in machine frame as (x, y, z, a, c, e) tuples per point + per-tool metadata) and emits text G-code. RRF dialect first. Emits:
- Header comments with metadata: bioink composition, cell type, cell density, total volume, estimated print time, sterility notes, max computed wall shear stress per syringe, user overrides if any.
- `G90`, `M83`, syringe-specific startup (e.g., `M104 S<temp> T<n>`), `G92 A0 C0` after operator confirmation.
- `G1 X… Y… Z… A… C… E… F…` per the Open5X token order (see `OPEN5X_NOTES.md` §4).
- Tool-change blocks via `T<n>` plus authored `tpre/tpost/tfree` macros.

**`visualization`** — `pyvista`-based 3D toolpath preview with tool orientation vectors. Layer-by-layer animation. Stress overlay. Deferred to phase 5; v1 ships a stub module so imports work but the function is `NotImplementedError`.

**`profile`** — `MachineProfile` dataclass: build volume, axis limits, feed caps, kinematic chain spec, default startup-block customisations. YAML-loaded from `bioslice5x/profile/library/*.yaml`. Ships with `open5x_prusa.yaml`, `open5x_voron.yaml`.

**`errors`** — Domain-specific exceptions. `CellViabilityError` carries: segment ID, computed stress (Pa), threshold (Pa), bioink name, cell type, suggested remediations (lower feed, larger gauge, lower viscosity bioink). Errors are raised at the boundary between `pathing` and `postprocessor` — see §5.

**`cli`** — `bioslice5x slice <mesh> --profile <profile.yaml> --recipe <recipe.yaml> -o <out.gcode>`. The `recipe.yaml` is the human-authored input: which syringes carry which bioinks, target surface, slicing parameters, cell-payload metadata.

---

## 3. Data Flow

```
mesh.stl ──┐
           ├──► geometry.load ──► Mesh
recipe.yaml┤                       │
profile.yaml──► profile.load ──► MachineProfile
           │                       │                              ┌─► path stress check ──► CellViabilityError?
           └──► geometry.slice_conformal(mesh, recipe.surface) ──► SlicedGeometry
                                                                  │  (ordered, curved slices in part frame)
                                                                  ▼
                                          pathing.generate(SlicedGeometry, recipe.syringes) ──► PartFramePath
                                                                  │
                                                                  ▼
                                          kinematics.transform(PartFramePath, profile.kinematic_chain) ──► MachinePath
                                                                  │  (X, Y, Z, A, C, joint angles per point)
                                                                  ▼
                                          extruder.annotate(MachinePath, syringes) ──► AnnotatedMachinePath
                                                                  │  (adds E values, per-segment flow rate, shear)
                                                                  ▼
                                          bioink.validate(AnnotatedMachinePath) ──► raises CellViabilityError on violation
                                                                  │
                                                                  ▼
                                          postprocessor.emit_rrf(AnnotatedMachinePath, profile) ──► out.gcode
```

Each arrow is a pure function call; nothing mutates the input. Every intermediate is a typed dataclass so the pipeline is unit-testable at every seam.

---

## 4. Design Decisions

### 4.1 Extrusion: displacement first, pneumatic later behind an `Extruder` interface

**Decision:** Ship `DisplacementSyringe` in v1. The E axis in G-code carries microliters of displaced bioink; the post-processor converts µL to plunger millimetres via `steps_per_uL` (computed from syringe inner diameter and stepper resolution) and emits the result as a delta on each G1 line (`M83` relative-extrusion mode, mirroring Open5X).

**Why:** Maps 1:1 to RRF's E-axis semantics, requires no custom M-codes in v1, matches Open5X's G-code structure exactly so existing RRF tooling (PrusaSlicer-like host software, RepRapFirmware Configuration Tool) sees nothing weird. Pneumatic systems need custom M-codes for pressure setpoint and dwell, plus a per-bioink calibration curve (pressure × time → volume). That's a substantial side-quest and not on the critical path.

**Interface:** `Extruder` is a Protocol with `prepare_segment_extrusion(segment) → ExtrusionCommand`. `ExtrusionCommand` is a tagged union: `EAxisDelta(uL)` for displacement, `PressurePulse(kPa, ms)` for pneumatic. The post-processor branches on tag; everything upstream is mode-agnostic. Adding pneumatic in v2 is "implement `PneumaticSyringe(Extruder)` and a `PressurePulse` emitter in `postprocessor/rrf.py`."

### 4.2 Bioink storage: typed dataclasses + YAML loader

**Decision:** Define `Bioink`, `RheologicalModel`, `CellPayload` as Python dataclasses in `bioink/models.py`. Ship a YAML loader (`bioink/library.py`) that reads `bioink/library/*.yaml` at startup. Users add new bioinks by dropping YAML files; wet-lab contributors don't touch Python.

**Why:** Best of both worlds. Mypy-strict-safe core, IDE autocomplete, runtime schema validation via the dataclass constructor. YAML files are diff-friendly, reviewable, and accessible to non-Python collaborators — this matters because bioink characterization is a wet-lab activity and we want PRs from people who don't write Python.

**Sketch (representative; actual fields finalized when implementing):**

```python
@dataclass(frozen=True)
class RheologicalModel:
    kind: Literal["newtonian", "power_law", "herschel_bulkley"]
    viscosity_pa_s: float | None = None      # newtonian
    consistency_k: float | None = None       # power_law / HB
    flow_index_n: float | None = None        # power_law / HB
    yield_stress_pa: float | None = None     # HB only

@dataclass(frozen=True)
class CellPayload:
    cell_type: str                            # e.g. "hiPSC-CM", "hMSC", "HEK293"
    cell_density_per_mL: float
    max_wall_shear_stress_pa: float           # the hard cell-safety limit

@dataclass(frozen=True)
class Bioink:
    name: str
    density_g_per_mL: float
    rheology: RheologicalModel
    working_temperature_c: tuple[float, float] # storage_low, print_high
    crosslinking: Literal["thermal", "ionic", "photo", "enzymatic", "none"]
    notes: str = ""
```

YAML example (`bioink/library/collagen_i.yaml`):

```yaml
name: collagen_i_8mg_per_mL
density_g_per_mL: 1.04
rheology:
  kind: power_law
  consistency_k: 80.0       # approximate; per BIOPRINTING_REQUIREMENTS.md §3
  flow_index_n: 0.1
working_temperature_c: [4.0, 25.0]
crosslinking: thermal
notes: "Acidified collagen I, gels above ~20 C. Conservative defaults; verify per-lot."
```

Cell-line limits ship in a separate file (`bioink/library/cells.yaml`) so a single bioink can be paired with multiple cell types at recipe time.

### 4.3 Cell-safety enforcement: hard refusal, not a warning

**Decision:** `bioink.validate(annotated_machine_path)` walks every segment, computes wall shear stress from the segment's flow rate and the assigned syringe's needle + bioink, and **raises `CellViabilityError` on the first segment that exceeds `cell_payload.max_wall_shear_stress_pa`.** The error message names the segment, the computed stress, the threshold, the limiting bioink/cell pair, and a remediation hint. The G-code file is **not written**.

The validation step runs *between* path generation and G-code emission. A `--force` CLI flag exists for development/debugging only; it changes the error to a `UserWarning` and writes a G-code file whose header comments are tagged `CELL_VIABILITY_FORCE_OVERRIDE`. This is *not* a production path — the override is loud in the file itself.

**Why:** The brief is unambiguous: "Cell viability is a hard constraint, not a print quality knob." Soft warnings get ignored. Putting the check at the path-validation boundary keeps it cheap (one pass, after the math is settled) and means every output file is provably under-threshold or explicitly tagged as not.

**Shear-stress computation (v1):**
- Newtonian default: `τ_wall = (4·μ·Q)/(π·r³)` for flow rate Q, dynamic viscosity μ, needle inner radius r.
- Power-law: `τ_wall = K · ((3n+1)/(4n))^n · (4Q/(π·r³))^n` — the Rabinowitsch-Mooney correction.
- Herschel-Bulkley: closed-form per Skelland 1967; if implementation gets hairy, fall back to a numerical solver in v1 and improve in v2.
- Extensional stress at the syringe-to-needle contraction is *not modelled* in v1; we instead warn on contraction ratios > 100:1 (per `BIOPRINTING_REQUIREMENTS.md` §4).

### 4.4 Kinematics: canonical tilt/swivel coordinates, A+C as the default labelling

**Decision:** The `kinematics` module operates in canonical generalized coordinates `(tilt_angle_rad, swivel_angle_rad)`, never in G-code letters. Letters are applied at the postprocessor stage via the machine profile. v1 ships `TiltSwivelKinematics` (tilt about world X, swivel about world Z by default) plus the `three_axis` no-rotary case for Phase 2a. Both implement the `KinematicChain` Protocol; path generation calls only the Protocol.

**Why:** A user running a Voron-style B+C machine should not need to touch math to get correct G-code. Letter-mapping at the I/O boundary is cheap to design in now and painful to retrofit. See §8.1 for the profile-level configuration.

The default A↔X, C↔Z convention matches Open5X's original Prusa Version_Save config (per `docs/OPEN5X_NOTES.md` §2). Sign convention is right-hand rule by inference; the per-axis `invert` flag in the profile is the one-line fix if hardware commissioning reveals an inverted sign.

### 4.5 Tool change for multi-syringe

**Decision:** Tool-change generates a fixed three-phase sequence: (1) retract along the current tool's last orientation to clear the deposited region; (2) reposition to a per-syringe purge station (defined in machine profile); (3) execute pre-defined `tpre<n>.g` / `tpost<n>.g` macros if present; (4) optional dwell for crosslinking. Purge volumes are bioink-specific and live in the bioink record.

Open5X's upstream macros are empty stubs (per `OPEN5X_NOTES.md` §4), so BioSlice5X ships its own templates.

---

## 5. Validation Strategy

- **Pure-function units** at every pipeline seam: mesh load, slicer, kinematic transform, extruder annotation, bioink validation, G-code emit. Each has known-answer tests with hand-computed expected outputs.
- **Round-trip kinematic tests**: `inverse(forward(pose)) == pose` to within numerical tolerance, across a Sobol-sampled grid of valid (x, y, z, a, c) configurations.
- **Singularity coverage**: tests assert that paths through known singular configurations are flagged.
- **Cell-viability tests**: synthetic recipe with a bioink + cell pair tuned to be exactly at the threshold; assert `CellViabilityError` raised. Tune flow rate down by 1%; assert no error. This is the most important regression test in the codebase.
- **Golden G-code**: a small set of recipes whose G-code output is checked into the repo; CI diffs against the golden. Open5X-equivalent samples + BioSlice5X-specific multi-syringe samples.
- **Lint/type discipline**: `ruff check`, `ruff format --check`, `mypy --strict` all run in CI; PRs blocked on failure.

---

## 6. Phasing

See §9 below for the revised phase plan (Phase 2 split into 2a–2d per reviewer guidance).

---

## 7. Resolved Decisions (from reviewer)

1. **Recipe schema**: YAML 1.2, pydantic v2 validation, JSON Schema export for IDE autocomplete. YAML chosen for comment support (lab notebooks need "concentration is from the 2024 prep, retest if changed"-style annotations) and readable nested structure for multi-material region assignments. TOML rejected as too verbose for nested mesh-region-to-bioink mappings.
2. **Singularity strategy**: smooth-through, not avoid. The A ≈ 0 / C-degenerate position is the rest pose for plate-on-bed and will be traversed on nearly every print. Detect when `|A| < singularity_threshold_deg` (default **2°**), linearly interpolate C across the singular region, log a warning naming the segment. No reject mode — soft hydrogels tolerate small orientation jitter and a "refuse" path is a footgun.
3. **Profile library scope**: ship **5 reference bioinks** — collagen I, GelMA, fibrin, alginate, PEGDA. Each carries viscosity, power-law n/K, max wall shear for two cell baselines (**HUVEC/endothelial** and **general mammalian**), working temperature, gelation mechanism, and source citations as YAML comments. Five covers the FRESH workhorse (collagen + fibrin), DLP standard (GelMA + PEGDA), and the cheap extrusion default (alginate) — enough to onboard most labs without committing to a library we have to actively maintain.
4. **Bath model**: deferred to v2 — an honest bath-drag model requires empirical calibration per bath formulation and per bioink, and shipping a wrong model is worse than shipping no model. v1 exposes **one knob**: `travel_speed_reduction_in_bath` (default 0.5), documented as "first-order bath drag handling, replace with proper model in v2." Operators running this in earnest will hand-tune anyway.
5. **CLI vs. library**: **library-first, CLI as thin shim**. Every CLI verb maps 1:1 to a public library call (`bioslice5x slice` → `Slicer(profile, recipe).slice(mesh)`). Reasons: Jupyter is the dominant bioprinting research workflow (parameter sweeps, recipe optimization), testing is dramatically simpler against a library API than subprocess invocation, and embedding BioSlice5X into a higher-level pipeline downstream is much easier with a real Python surface. CLI exists for reproducibility and non-Python users; the library is the product.

## 8. Pre-Phase-2 Architectural Additions (from reviewer feedback)

### 8.1 Canonical axis naming, letter mapping at the postprocessor

The `kinematics` module operates in **canonical generalized coordinates**, not G-code letters:

- `tilt_angle_rad` — the bed-tilt joint (Open5X-equivalent of A, B, or U depending on chassis variant)
- `swivel_angle_rad` — the plate-rotation joint (Open5X-equivalent of C or V depending on variant)

The machine profile YAML carries the mapping at the I/O boundary:

```yaml
kinematic_chain:
  kind: tilt_swivel             # vs. "three_axis" for the 2a baseline
  tilt:
    rotates_about: x            # world axis
    letter: A                   # G-code letter
    invert: false               # negate command sign if hardware is mirrored
    range_deg: [-110, 110]
  swivel:
    rotates_about: z
    letter: C
    invert: false
    range_deg: [-360000, 360000]
```

The kinematics module never sees the letters. The postprocessor reads `profile.kinematic_chain.tilt.letter` and substitutes at G-code emit time. A Voron operator changes `letter: A` → `letter: B` and no kinematics code is touched.

**The `invert` flag is the one-line fix for the right-hand-rule commissioning check** (see `docs/OPEN5X_NOTES.md` §2 callout).

### 8.2 Library-first surface

Top-level public API (frozen in v1):

```python
from bioslice5x import Slicer, load_profile, load_recipe, load_mesh

profile = load_profile("open5x_prusa")          # or a path
recipe  = load_recipe("recipes/my_print.yaml")
mesh    = load_mesh("models/heart_chamber.stl")

slicer = Slicer(profile=profile, recipe=recipe)
result = slicer.slice(mesh)                     # returns SliceResult, not a string
gcode  = result.gcode                           # str
report = result.cell_stress_report              # structured stress summary

# convenience
result.write_gcode("out.gcode")
```

`SliceResult` carries the G-code, the cell-stress report, total volume, estimated print time, and per-segment metadata. The CLI's `bioslice5x slice <mesh> --profile <p> --recipe <r> -o <out>` is a 30-line `cli.py` that calls exactly this.

### 8.3 Cell-viability shear-stress formula (v1 = Newtonian, conservative-ish)

v1 ships the Newtonian wall-shear-stress formula `τ_w = (4·μ·Q)/(π·r³)` using each bioink's **zero-shear (bulk) viscosity** as μ. For shear-thinning fluids (n < 1, which is collagen and GelMA at typical printing concentrations) the Rabinowitsch-corrected wall stress can differ by a factor of 2–3 from this Newtonian estimate. Per reviewer guidance: with bulk viscosity as the input, the Newtonian estimate over-predicts wall stress because the real shear-thinned viscosity at the wall is lower — so a "safe" Newtonian result is more likely safe in reality. v2 replaces this with power-law/Herschel-Bulkley Rabinowitsch-Mooney corrections.

This caveat is in the docstring of `extruder/shear.py` and on every emitted G-code header.

### 8.4 Bioink `calibrated_against` metadata

Reproducibility for downstream publishing. Every `Bioink` and `CellPayload` carries:

```yaml
calibrated_against: "uncalibrated, literature default"   # or:
# calibrated_against: "Feinberg lab, 2024-Q3, hUVEC at 5e6/mL, single-arm extrusion viability assay, n=3"
```

The string lands in the G-code header and the cell-stress report. PRs adding new bioinks should populate this; the default makes the placeholder-status explicit.

### 8.5 Recipe schema: single-bioink-whole-mesh is N=1 of the general form

The recipe data model uses **regions** from the start, even though 2a only exercises one. A syringe owns a `Region`:

```yaml
syringes:
  - id: 0
    bioink: collagen_i_8mg_per_mL
    cell_payload: general_mammalian
    needle: { inner_diameter_mm: 0.26, length_mm: 12.7 }
    region: { kind: all }              # 2a trivial case
  # 2d adds:
  # - id: 1
  #   bioink: gelma_10pct
  #   ...
  #   region: { kind: bbox, min: [0, 0, 0], max: [10, 10, 5] }
```

`Region.kind = "all"` matches every triangle of the mesh; future kinds (`bbox`, `submesh`, `volume_fraction`) are siblings under the same dispatch. The slicer's per-layer toolpath generator queries each syringe's region for the geometry it owns — same code path regardless of N.

### 8.6 Dry-run mode for hardware commissioning

`bioslice5x dry-run <mesh> --profile <p> --recipe <r> -o <out> --moves N` emits only the first N moves of the slice to a sidecar G-code file with no bioink loaded. Used to verify the right-hand-rule sign assumption against fresh hardware (see `docs/OPEN5X_NOTES.md` §2). The library API is `slicer.slice(mesh).dry_run(n_moves=N)`.

## 9. Phasing (revised — Phase 2 split into 2a–2d)

- **Phase 1** (✅ shipped): docs + scaffolding.
- **Phase 2a** (this PR): 3-axis baseline. Mesh I/O → flat horizontal slicing → straight-line paths → RRF G-code with volume-based E. Single syringe, single bioink (N=1 of the multi-region form). Validates pipeline shape before adding kinematic complexity.
- **Phase 2b**: 5-axis kinematics. Canonical (tilt, swivel) inverse kinematics, tool orientation per path point, smooth-through singularity handling. Paths still flat-sliced.
- **Phase 2c**: Conformal slicing. Curved layers along surface normals — wrap-around-axis mode first, then arbitrary curved layers.
- **Phase 2d**: Multi-syringe coordination. N > 1 regions, tool-change G-code, per-syringe retract/purge, dwell-for-crosslinking. CHIPS-style multi-material territory.
- **Phase 3**: Visualization + the cell-stress report. Pyvista preview, layer animation, structured stress overlay.

Each phase ends with a STOP-and-review checkpoint.
