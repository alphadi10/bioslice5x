# Known limitations as of v0.1.0

This document lists what BioSlice5X v0.1.0 deliberately does not do.
Anything here is either filed for a future version or out of scope per
the project's design philosophy.

## Calibration

**All shipped reference values are uncalibrated.** Bioink rheology
(`collagen_i_8mg_per_mL`, `gelma_10pct`, `fibrin_25mg_per_mL`,
`alginate_3pct`, `pegda_20pct`), cell-shear thresholds
(`general_mammalian`, `hUVEC_endothelial`), and bath drag multipliers
(`gelatin_microparticle_default`) all carry
`calibrated_against: "uncalibrated, literature default"`. The G-code
header surfaces this. Validate against your lab's empirical data before
publication-grade work.

## Geometry & slicing

- **Conformal slicing is wrap-around-axis only** (cylindrical shells around
  a chosen world axis). Fully arbitrary curved layers
  (surface-normal-following with arbitrary base geometry) is a CGAL-class
  geometry problem deferred to v0.3.0+.
- **Wrap-around-tilt-axis** requires either an arc that fits within the
  profile's tilt range or explicit `allow_tilt_arc_split` opt-in. See
  ADR-001.
- **The conformal slicer assumes a roughly-cylindrical mesh** along the
  wrap axis. Non-cylindrical meshes with `wrap_around_axis` mode produce
  paths that ignore the actual mesh radius variation. Mesh-aware radial
  sampling is a v0.2.0 follow-up.
- **Flat-mode infill** ships at v0.1.0; the same scan-line generator
  works on conformal layers in principle but the conformal-infill lift
  is wired as v0.1.1.

## Multi-syringe

- **Only `Region(kind="all")` is implemented.** Every syringe prints the
  entire mesh. `Region(kind="bbox")` (axis-aligned bounding-box
  intersection) and `Region(kind="submesh")` (named submesh in
  multi-object STL/OBJ) are reserved in the schema and will be
  implemented in v0.1.1.
- **No per-bioink retraction or priming** at tool change. The `T<n>`
  G-code line switches the tool; bioink-specific retract volumes and
  prime sequences are v0.1.1.
- **Naive layer ordering** — all of syringe 0's work, then all of
  syringe 1's, etc. Smart cross-region travel minimization is a v0.1.1
  optimization, filed as a known good-quality issue not a correctness
  issue.

## Bath modeling

- **Plane bath only.** `PlaneBath` (horizontal surface at a chosen Z) is
  the v0.1.0 model; dish and custom-surface kinds are reserved in the
  `BathSurface` Protocol but not implemented.
- **Travel-speed reduction is a single multiplier**, not a true
  Herschel-Bulkley bath-drag formula. The latter needs empirical
  calibration per bath formulation that v0.1.0 does not have. The single
  knob is documented as a first-order placeholder.
- **No path-segment-aware bath averaging.** A travel that crosses the
  bath surface uses the multiplier from the move's endpoint, not an
  integrated average. Acceptable for most real prints; revisit if needed.

## Cell-viability model

- **Newtonian wall-shear-stress only.** Power-law and Herschel-Bulkley
  rheology fits are loaded from YAML but the validation uses the
  Newtonian formula with the bioink's bulk viscosity. Per the
  conservative-direction analysis (`extruder/shear.py`), this
  over-predicts stress for shear-thinning bioinks — safe rejections
  are less likely to be wrong than unsafe approvals. Rabinowitsch-Mooney
  corrections are v0.2.0.
- **No extensional-stress check** at the syringe-to-needle contraction.
  Bath review guidance warns at 100:1 area ratio; we surface the ratio
  in the G-code header but do not gate on it.

## G-code dialect

- **RepRapFirmware (RRF) only.** Marlin dialect is v0.2.0. The
  postprocessor is structured so a sibling `MarlinEmitter` is a clean
  addition.
- **No support for pressure-based extrusion.** Displacement-driven
  syringes only. Pneumatic systems (Cellink/Allevi-style) would use
  `M42` valve control + pressure setpoints; the architecture supports
  this via a sibling `Extruder` Protocol implementation deferred to
  v0.2.0+.

## Python version

- **Python 3.11+ required for G-code emission.** Earlier Pythons can
  import the package and run most submodules but `emit_rrf` raises a
  clear `RuntimeError` (see `CONTRIBUTING.md` §Python versions).

## Tooling

- **Minimal GUI.** A Tkinter wrapper with file pickers, slice button,
  a PyVista-backed "Preview toolpath" launcher, and Phase 5 viewer
  options (color mode, mesh overlay). Full PrusaSlicer-style settings
  panel with an inline recipe editor and embedded build-area mesh
  viewer is Phase 6+.
- **Toolpath viewer (Phase 4 + Phase 5)** now ships layer scrubbing,
  shear-stress coloring (via `;STRESS:<Pa>` G-code tokens), and
  semi-transparent source-mesh overlay. See ADR-005. Outstanding viewer
  items: animated print-sequence playback, per-syringe segment coloring
  in multi-syringe prints, segment-picking with a metadata panel, and
  frame-aware mesh overlay for fixed-tilt prints (the mesh currently
  renders in part frame, offset from the machine-frame toolpath).
- **No live print monitoring.** The G-code is a static artifact; closed-
  loop sensing is out of scope for the slicer.
