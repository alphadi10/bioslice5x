# ADR-005: Phase 5 viewer scope — stress coloring, layer scrubbing, mesh overlay

**Status:** Accepted.
**Date:** 2026-05-11.
**Companion test:** `tests/test_preview_smoke.py`.
**Builds on:** [ADR-004](0004-toolpath-viewer-backend.md).

## Context

ADR-004 picked PyVista as the rendering backend and shipped a v0.1.0
toolpath viewer that reads G-code and renders extrusion moves colored
by Z, travel moves as grey segments, tool-orientation arrows on
sampled extrusion points, and an optional build-volume wireframe. The
viewer is intentionally G-code-parser-based so it stays decoupled from
the slicer's in-memory `SliceResult`.

ADR-004 explicitly deferred three features to Phase 5:

1. **Per-segment wall-shear-stress coloring** — the bio-specific win,
   directly motivated by the cell-viability hard constraint
   ([BIOPRINTING_REQUIREMENTS.md §4](../BIOPRINTING_REQUIREMENTS.md)).
   Without it, the viewer can show the operator *where* the toolpath
   goes but not *whether the cells survived it*.
2. **Layer scrubbing** — the single most-requested PrusaSlicer-equivalent
   feature. A slider that controls how many layers of the print are
   visible, so the operator can walk through the print layer by layer.
3. **Source-mesh overlay** — render the original STL semi-transparent
   alongside the toolpath, so the operator can compare "what was asked
   for" against "what was sliced."

This ADR records the design decisions for each.

## Decisions

### 5.1 Stress coloring via a `;STRESS:<Pa>` G-code token

**Decision:** The RRF postprocessor emits a `;STRESS:<Pa>` trailing
comment on every extrusion G1 line. The viewer's parser captures this
into `ParsedMove.wall_shear_pa`. When the viewer is invoked with
`color_by="shear"`, the colormap (`hot`) is keyed off this scalar.

**Why this and not the alternatives:**

- **(a) `SliceResult`-based viewer.** Would route the viewer through
  the slicer's in-memory annotated path, no parsing needed. Pro: cleaner
  data flow, no text round-trip. Con: viewer only works on freshly
  sliced material, not third-party G-code or files opened a week later.
  ADR-004 deliberately split the viewer from the slicer for exactly this
  reason — preserving that split was load-bearing.
- **(b) A sidecar `.stress.json` file.** Pro: keeps G-code clean. Con:
  introduces a second artifact that can drift out of sync with the
  G-code; defeats the "G-code is the deterministic, reviewable output"
  principle (ARCHITECTURE.md §8.4).
- **(c) G-code token, chosen.** Pro: the stress lives in the same
  artifact as the move it describes; cannot drift. The token is a comment
  (RRF and Marlin both treat `;…` as ignorable past the semicolon), so
  printers ignore it. Pro: third-party G-code without the token parses
  cleanly with `wall_shear_pa=None`, and the viewer falls back to z-color
  mode automatically. Con: very small file-size overhead (~20 bytes per
  extrusion move; a 10k-move print adds ~200 KB).

The shear-coloring colormap is clamped to `[0, threshold]` when the
caller supplies `cell_stress_threshold_pa` (typically from the recipe's
active cell payload), so red on the colorbar marks the cell-viability
limit exactly. Without a threshold, the colormap auto-fits.

### 5.2 Layer scrubber via PyVista `add_slider_widget`

**Decision:** The viewer adds a PyVista slider (bottom-left of the
window) labeled "Layers shown (0..N)". Dragging the slider down hides
later-printed segments; dragging back up reveals them. The callback
re-renders the extrusion actor with a threshold filter on the
per-segment `layer_index` cell-data array.

**Layer-index assignment is dual-mode:**

- **Z-banded mode** (flat / wrap-around-Z prints): bin extrusion moves
  by rounded Z (10 µm tolerance). Each distinct rounded-Z is one layer.
  Matches the slicer's `layer_height_mm` for flat-mode prints.
- **Ordinal-band fallback** (conformal / 5-axis prints with continuously
  varying Z): when there are too many distinct Z values for the Z-banded
  scheme to produce a useful scrubber (heuristic: more than 1 distinct
  Z per 5 moves), split the slicer-emitted move sequence into 100
  equal-count bands. The scrubber still works; it just maps to time-in-print
  rather than physical layers.

The slider is disabled in screenshot / off-screen rendering mode (no
VTK interactor to back the widget) and when the print has only one
layer (trivial scrubber adds no information).

### 5.3 Source-mesh overlay

**Decision:** The viewer accepts an optional `source_mesh_path` (STL or
OBJ via trimesh, the same loader the slicer uses). The mesh is rendered
as a semi-transparent (default opacity 0.15) light-blue actor behind
the toolpath. CLI flag: `--mesh <path>` + `--mesh-opacity <f>`.

Failure to load the mesh (missing file, malformed STL) is non-fatal:
the rest of the scene renders and the info overlay surfaces the load
error. Operators can pre-flight mesh issues without losing their
toolpath view.

**Frame alignment caveat:** The mesh is rendered in its native
coordinate frame (the part frame). The G-code toolpath is in machine
frame. For flat-orientation prints these are the same; for prints with
a fixed-tilt orientation the mesh appears offset from the toolpath.
This is documented in the help text and the info overlay. A
mesh-frame-to-machine-frame transform is deferred to v0.2.x; the
data we need (the recipe's `print_orientation`) is not in the G-code
header today, and adding it would couple the viewer back to the slicer.

## Out of scope (deferred to later phases)

- **Animation of the print sequence.** A play/pause button driving the
  layer slider. Easy add on top of the scrubber; punted to v0.2.0 polish.
- **Per-syringe coloring in multi-syringe prints.** Currently shear and
  Z each take the single scalar slot. A "syringe_id" mode is one
  `ParsedMove` field away.
- **Picking** (click a segment to see its move metadata in a panel).
  PyVista supports it; not needed for v0.2.0.
- **Embedding the viewer in a Qt window** alongside a settings panel
  (Phase 6+). `pyvistaqt` is the path; the current free-standing window
  is a stepping stone.
- **Frame-aware mesh overlay** for tilt-prints. Needs the recipe's
  `print_orientation` plumbed into the G-code header.

## Validation

- **Parser round-trip:** `tests/test_preview_smoke.py` asserts that
  fresh slicer output carries `;STRESS:` on every extrusion move and
  that the parser reads it back into `ParsedMove.wall_shear_pa`.
- **Backwards compatibility:** the same test file asserts that G-code
  without stress tokens parses cleanly (`wall_shear_pa=None`) and that
  the viewer falls back to z-color mode.
- **Layer-index banding:** unit tests cover both the Z-banded path (3
  layers × 5 moves → ranks [0,1,2]) and the conformal-fallback path
  (500 distinct Zs → 100 ordinal bands).
- **Mesh overlay:** smoke tests render a cube STL on top of a cube
  toolpath, and verify that a bad mesh path is non-fatal.
- **End-to-end:** the CHIPS pancreatic reference recipe slices and
  renders through the full pipeline (shear coloring + MIN6 1.5 kPa
  threshold + mesh overlay) without crashing — verified manually and
  via the screenshot tests.

## File-by-file impact

| File | Change |
|---|---|
| `src/bioslice5x/postprocessor/rrf.py` | Emit `;STRESS:<Pa>` per extrusion G1. |
| `src/bioslice5x/visualization/preview.py` | `ParsedMove.wall_shear_pa`; `ColorMode` literal; `_compute_layer_indices`; slider widget; mesh-overlay actor. |
| `src/bioslice5x/cli.py` | `--color-by`, `--stress-threshold-pa`, `--mesh`, `--mesh-opacity`. |
| `tests/test_preview_smoke.py` | Stress-token, layer-band, mesh-overlay tests. |
| `tests/golden/flat_mode_2a_cube.gcode.golden` | Regenerated to include `;STRESS:` annotations. |
