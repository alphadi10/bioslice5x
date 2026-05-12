# ADR-004: 3D toolpath viewer backend

**Status:** Accepted.
**Date:** 2026-05-11.
**Companion test:** `tests/test_preview_smoke.py`.

## Context

Phase 4 adds the first visual artifact to BioSlice5X: a 3D viewer for the
G-code the slicer produces. Researchers can inspect the toolpath before
committing cell payload to a print. The viewer is also the foundation for
Phases 5–7 (mesh viewer, settings panel, full app).

The single biggest design decision is the 3D rendering backend.

## Considered alternatives

### (a) PyVista (chosen)

VTK-based scientific 3D visualization for Python. Already an optional
dependency (`[project.optional-dependencies] viz = ["pyvista>=0.43"]`).

- **Pros:** Native desktop window, mature, used by FreeCAD-adjacent
  scientific Python. Built-in primitives for lines, arrows, slider
  widgets, picking, screenshots. Good performance for 10⁴–10⁵ segments
  (single-mesh toolpath cube is ~500 moves, conformal cylinder ~1000;
  largest realistic FRESH prints will be ~10⁴–10⁵ moves). Plays well
  with Qt for Phase 5 embedding (`pyvistaqt`).
- **Cons:** VTK installation is heavyweight (~80MB) and notoriously
  fiddly on some platforms (Apple Silicon historically had issues, now
  mostly resolved). Headless rendering for CI requires xvfb.

### (b) Three.js + browser frontend

JavaScript 3D in a browser window, communicated with via WebSocket.

- **Pros:** Beautiful out of the box. Modern controls. No native install
  pain.
- **Cons:** Distribution complexity (must bundle Node toolchain, or
  serve a static page from the Python process). Phase 5 wants embedded
  3D in a settings panel — much harder when the viewer is in a browser.
  No native file-pick integration. Diverges architecturally from the
  rest of the project, which is pure Python.

### (c) matplotlib mplot3d

The default Python 3D plot toolkit.

- **Pros:** Zero extra dependencies. Familiar to scientists.
- **Cons:** Software rendering only — chokes above ~10⁴ line segments.
  No native interaction primitives (slider, arrows, mesh picking).
  Cannot reasonably scale to the full FRESH workloads. Would be a dead
  end the moment we ship anything more complex than the demo cube.

### (d) Open3D

Modern alternative to PyVista, growing scientific-Python adoption.

- **Pros:** Faster than VTK for large point clouds; nicer modern API for
  some operations.
- **Cons:** Less mature for line-and-arrow rendering, fewer widget
  primitives, harder Qt embedding story. Smaller community.

## Decision

**(a) PyVista.** Reasons:

1. **It's already in `pyproject.toml` as an optional extra.** Adopting it
   for Phase 4 means promoting `viz` from optional to required — a single
   line change. No architectural pivot.
2. **The Qt embedding path is well-trodden.** `pyvistaqt` is a tiny
   shim that puts a PyVista plotter inside a QWidget. Phase 5 (full
   PySide6 app) gets the same renderer as Phase 4 (standalone viewer)
   without rewriting any rendering code.
3. **Scientific Python alignment.** Researchers using this tool will
   already have PyVista or be one `pip install` away from it, because
   FreeCAD, ParaView, and most medical imaging libraries are VTK-based.
4. **Cell-safety overlay is naturally expressible.** Coloring lines by
   computed wall shear stress (a scalar field along the path) is one
   line of PyVista. Three.js would require custom shader code.

## Worked example (pinned by `tests/test_preview_smoke.py`)

A user runs:

```bash
bioslice5x preview cube.gcode
```

The viewer opens with:
- The build-volume bounding box rendered as a translucent grey wireframe
- Extrusion moves rendered as line segments, colored by Z-coordinate
  (cool layers blue, warm layers red)
- Travel moves rendered as a single grey dashed line bundle
- Tool-orientation arrows drawn at every 50th extrusion move (sampled
  from the A/C joint values in the G-code)
- A title bar showing the source filename, total moves, and max wall
  shear stress (read from the `;META:` header)
- Standard PyVista trackball controls (left-drag rotate, right-drag
  pan, scroll zoom)

Pressing 'q' or closing the window exits cleanly.

## Out of scope for ADR-004

- **Layer slider** — deferred to ADR-006 alongside the Phase 5 settings
  panel. The viewer launches showing all layers; scrubbing is a
  follow-up.
- **Shear-stress coloring** — the slicer's `SliceResult` carries
  per-move stress, but the G-code does not. To color by shear in
  Phase 4 we'd either embed a `;STRESS:` block per move in the G-code
  header (verbose) or take a `SliceResult` directly instead of parsing
  a file (no longer "standalone viewer"). Phase 5 wires the
  SliceResult-based path; Phase 4 colors by Z.
- **Mesh overlay** — Phase 5 deliverable. The Phase 4 viewer shows the
  G-code, not the source mesh. Adding mesh-loading here would muddle
  the smallest-useful-viewer scope.
- **Animation / build-time replay** — eventually useful, not v0.2.0.

## Rejection reasoning summary

- (b) Three.js — wrong architectural direction; bifurcates the codebase.
- (c) matplotlib — performance ceiling too low; project would outgrow
  it within one phase.
- (d) Open3D — comparable to PyVista on rendering but worse on the
  embedding story we need for Phase 5; no compelling advantage today.

## Forward compatibility

If PyVista ever proves wrong (e.g., VTK becomes unmaintainable, or a
clearly better backend emerges), the viewer is contained in
`bioslice5x.visualization.preview` and a sibling implementation slots in
under the same `ToolpathViewer` interface. The rest of the slicer never
imports PyVista.
