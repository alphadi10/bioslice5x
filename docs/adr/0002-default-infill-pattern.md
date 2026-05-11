# ADR-002: Default infill pattern

**Status:** Accepted.
**Date:** 2026-05-11.
**Companion test:** `tests/test_adr_002_examples.py`.

## Context

Phase 2c.2 introduces infill. The recipe's `slicing.infill_density` field
gates infill generation: 0.0 (default) → perimeter only; > 0.0 → infill
runs. The choice of *pattern* — rectilinear, concentric, gyroid, honeycomb,
adaptive cubic, etc. — has visible quality implications and is not a
narrow design space.

For v0.1.0, BioSlice5X must commit to exactly one default pattern. The
recipe schema reserves room for alternatives (`SlicingParams.infill_pattern`
will be an enum), but ships one implementation.

## Considered alternatives

### (a) Rectilinear (parallel scan-lines)

Parallel scan-lines at a configurable angle, intersected with the layer's
exterior boundary. Alternating-angle layers (45° / 135° / 45° / …) is the
common variant.

- **Pros:** simplest geometry (lines + polygon intersection). Well-known
  failure modes (corner-skipping, infill-perimeter weak bond). Works
  identically on flat and curved (s, θ) layers, satisfying the unified
  general-form rule.
- **Cons:** straight lines through a soft hydrogel kerf produce visible
  deposition artifacts at scan-line endpoints if the bath drag isn't
  perfectly handled. Lower mechanical strength than concentric or gyroid
  for the same fill density.

### (b) Concentric (inset perimeters)

Successive inward offsets of the layer's exterior boundary at line-width
spacing.

- **Pros:** continuous deposition (no scan-line endpoints inside the
  layer). Strong on the perimeter direction. Bath-friendly.
- **Cons:** offset operations on arbitrary 2D polygons need a robust
  polygon-offset library (CGAL or shapely-with-care); shapely's `.buffer`
  is suitable but produces curved arcs at concave corners that don't
  translate cleanly to a curved-layer (s, θ) parameter space. Different
  algorithm for flat vs. curved — violates the unified general-form rule.

### (c) Gyroid (triply periodic minimal surface)

3D mathematical surface intersected with each layer.

- **Pros:** isotropic strength, biologically suggestive (mimics
  trabecular bone, lung parenchyma). Aesthetic appeal in bioprinting
  papers.
- **Cons:** intersection at each layer is nontrivial; produces curves
  with second-derivative discontinuities that translate poorly through
  the kinematic transform. Significantly more complex implementation. Not
  obviously a v0.1.0 deliverable.

### (d) Adaptive / honeycomb / cross / triangular / …

A grab-bag of "advanced" patterns. Each has its tradeoffs and would be
worth a separate ADR if anyone asks. Not v0.1.0.

## Decision

**Default to rectilinear with 90°-alternating layer angle.**

Reasoning:

- Rectilinear is the **only pattern that uses the unified flat/curved
  scan-line generator** with no algorithm change. Implementing it on
  flat layers immediately gives a working conformal-layer implementation
  the moment the (s, θ) lift function is wired in (2c.3 if not in 2c.2).
- 90° alternation is the well-established default in FDM and adapts
  cleanly to bioprinting; alternative angles are exposed via
  `SlicingParams.infill_angle_deg` (default `0.0`, then layer N adds
  `90 * N`).
- Concentric and gyroid get their own ADRs if the request comes; this
  decision is not closed forever.

Cell-safety reasoning: none of (a)-(c) has direct cell-safety implications
distinguishing them — wall shear stress is computed per segment regardless
of pattern. The pattern affects deposition geometry, not shear envelope.

## Recipe schema

```yaml
slicing:
  layer_height_mm: 0.4
  line_width_mm: 0.5
  infill_density: 0.2        # 20% fill (0.0 = perimeter only)
  infill_pattern: rectilinear # the only kind in v0.1.0
  infill_angle_deg: 0.0      # base angle; layer N rotates by 90·N
```

## Worked example

A 10mm × 10mm square layer at 20% density with `infill_angle_deg = 0`
produces horizontal scan-lines at spacing `line_width_mm / infill_density
= 0.5 / 0.2 = 2.5 mm`. With the layer spanning `y ∈ [-5, 5]`, scan-lines
land at y = -3.75, -1.25, +1.25, +3.75 — four lines, each ~10 mm long,
total infill length ≈ 40 mm.

`test_adr_002_examples.py` pins this exact computation.

## Out of scope

- Multi-density per-layer infill (e.g., dense shell + sparse core).
- Variable-pattern infill (different pattern per layer).
- Infill on curved (s, θ) parameter-space layers — this is mechanically
  trivial once the lift function is wired; tracking as 2c.3 if not
  shipped in 2c.2.
- Bath-aware retraction at scan-line endpoints — the same single bath
  knob applies as for perimeter travels; per-segment-aware bath modeling
  is the v2 bath-drag follow-up.
