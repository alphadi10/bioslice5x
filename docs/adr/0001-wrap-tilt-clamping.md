# ADR-001: Wrap-around-tilt-axis clamping strategy

**Status:** Accepted, pending implementation in Phase 2c.1.
**Date:** 2026-05-11.
**Companion test:** `tests/test_adr_001_examples.py` (pins the worked examples
below so this doc cannot drift).

## Context

Phase 2c v1 ships `WrapAroundAxisSlicing(wrap_axis="z")` only — wrap around
the swivel rotation axis, which has effectively unbounded range on both
shipped profiles (Open5X Prusa: ±360 000°, Voron: ±360 000°). Full 360°
arcs are trivially printable.

Phase 2c.1 extends to `wrap_axis="x"` (Prusa A) and `wrap_axis="y"` (Voron
B). These are tilt axes with **finite mechanical range**: Prusa ±200°,
Voron ±110°. A full 360° wrap is mechanically impossible on Voron and
near-impossible on Prusa (200° < 360°). The slicer must decide what to do
when the recipe asks for an arc that exceeds the profile's tilt range.

The decision is user-visible — it affects whether a print succeeds, fails
loudly, or proceeds with quality-altering modifications.

## Considered alternatives

### (a) Sub-arc split with retraction

Split the requested arc into N sub-arcs, each within the tilt range,
separated by retract-clear moves. The bed unwinds during the retract so
the next sub-arc starts from a fresh tilt-at-zero pose.

- **Pros:** prints the full requested wrap. No arc is left unprinted.
- **Cons:** introduces deposition discontinuities at sub-arc boundaries —
  small kerf gaps where the needle disengaged and re-engaged. For
  cell-laden bioinks these are weak spots in the print. The retract
  motion also disturbs the bath kerf.

### (b) Refuse with a clear error

Detect at slice time that the requested arc exceeds tilt range. Raise
`ProfileValidationError` naming the affected sub-arc, the profile's tilt
range, and the user's options.

- **Pros:** fails fast, before any cell payload is loaded. No surprise
  deposition discontinuities. Forces the user to make an explicit choice.
- **Cons:** strictly less capable than (a) — useful prints get refused.

### (c) Tilt to max + continue rotation via swivel

When tilt reaches its limit, keep the tilt at its maximum and continue the
wrap by rotating the swivel axis instead. The bed orientation no longer
follows the part's surface normal exactly during the second part of the
arc; the toolhead is depositing at an angle.

- **Pros:** prints the full arc without retraction.
- **Cons:** **violates the FRESH "deposit perpendicular to the curved
  surface" principle**. The bath supports the print only when the needle
  is roughly normal to the deposition surface; tilted-but-deposit-anyway
  produces shear-stress profiles that aren't covered by the per-bioink
  shear-rate model. The slicer's cell-safety check would not catch the
  resulting risk because it computes wall shear assuming flow is along
  the needle axis. Silent quality degradation.

## Decision

**Combine (b) and (a). Default to refuse-loudly; opt-in to arc-split.**

Concretely:
- At slice time, if `abs(arc_end - arc_start) > profile.tilt.range`, raise
  `ProfileValidationError` with a message naming the requested arc, the
  available tilt range, the maximum number of sub-arcs that would fit
  within range, and a one-liner explaining the `--allow-arc-split` flag.
- The CLI flag `--allow-arc-split N` (or the equivalent recipe field
  `slicing.mode.arc_split_count`) opts into splitting the arc into N
  sub-arcs of equal angle. The slicer generates a retract-clear move
  between each pair of sub-arcs, with retract volume determined by
  `slicing.line_width_mm × slicing.layer_height_mm × profile.retract_clear_mm`.
- Strategy (c) is **rejected outright** on cell-safety grounds. It is not
  exposed via any flag, even with an `--unsafe-tilt-without-normal`
  escape hatch — the silent quality degradation is exactly the kind of
  footgun the project's design philosophy refuses to ship.

## Worked example (pinned by `tests/test_adr_001_examples.py`)

**Setup:** Voron profile, tilt range ±110° (total 220°). Recipe requests
arc from -180° to +180° (total 360°).

**Default behaviour (no flag):**

```
ProfileValidationError: arc_span 360° exceeds profile.tilt.range
  (-110°, +110°) — total available 220°. The minimum N that fits is
  ceil(360 / 220) = 2 sub-arcs. Re-run with --allow-arc-split 2 to
  proceed with arc-split + retraction between sub-arcs.
```

**With `--allow-arc-split 2`:**

Arc 1: -180° to 0° (span 180°). The slicer reparameterises: this sub-arc
starts at the part-frame θ that maps to the profile's tilt = -110° and
ends at tilt = +70°. Concretely for `wrap_axis="x"` (Prusa-style):

- θ_part runs from -180° to 0°. Tilt = -θ_part shifted into range: tilt at
  θ_part=-180° is +180°, which exceeds +110°. Split point: tilt = +110° →
  θ_part = -110°. Sub-arc 1 prints θ_part ∈ [-110°, 0°], tilt ∈ [0°, +110°].

Arc 2: θ_part ∈ [-180°, -110°] OR [0°, +180°] (the leftover). With tilt
range ±110°, this is two more sub-arcs to fit, contradicting N=2. Hence
the validation error: N=2 is insufficient; the minimum is N=4 for full
360° on Voron's ±110° range.

The example is admittedly thorny — the test pins three scenarios with
expected outputs (the error message text for the default path, the
sub-arc count and angle list for the explicit-N path, and the rejection
of N too small) so the implementation does what this doc says.

## Out of scope for this ADR

- Retract-volume estimation under bath-drag for the inter-sub-arc travels.
  Lands with the v2 bath-drag model.
- Mid-print pause for user-confirmed tilt unwind. Not on the roadmap.
- Multi-axis combined wraps (wrap simultaneously around tilt and swivel).
  Future ADR if needed.

## References

- `docs/OPEN5X_NOTES.md` §2 — VERIFY AT COMMISSIONING for tilt sign.
- `docs/BIOPRINTING_REQUIREMENTS.md` §4 — cell viability under shear; the
  reason strategy (c) is rejected.
- `docs/PHASE_2B_NOTES.md` §5 — singularity smooth-through, which is
  related but operates on a different axis (swivel under low tilt, not
  tilt approaching its limit).
