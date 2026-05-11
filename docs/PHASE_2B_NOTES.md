# Phase 2b — A/C Kinematic Transform Notes

**Scope:** the A/C (or B/C, U/V, …) inverse kinematics is correct. Flat slicing,
single perimeter, single syringe — all the same as Phase 2a. No infill, no
multi-syringe, no conformal layers. Phase 2c adds curvature; Phase 2d adds
multi-syringe coordination.

**Companion docs:** [`OPEN5X_NOTES.md`](OPEN5X_NOTES.md) §2 for the right-hand-
rule commissioning check; [`../ARCHITECTURE.md`](../ARCHITECTURE.md) §8.1 for
the canonical-naming abstraction and §4.4 for the KinematicChain Protocol.

---

## 1. The single load-bearing principle

**Kinematics works in canonical `(tilt_rad, swivel_rad)`. The postprocessor
maps to G-code letters.** Nothing in `bioslice5x/kinematics/` knows that the
joint *might* be called A, B, U, or anything else. The mapping lives in the
machine profile YAML and is applied at exactly one point — `_axis_token` in
`postprocessor/rrf.py`.

This is what lets a Voron user swap profiles without touching code: the
kinematic transform produces the same machine-frame X/Y/Z and the same
canonical (tilt, swivel) regardless of letter naming.

## 2. Worked example: A+C profile (Open5X Prusa)

`open5x_prusa.yaml`:

```yaml
kinematic_chain:
  kind: tilt_swivel
  tilt:
    rotates_about: x
    letter: A
    invert: false
    range_deg: [-200.0, 200.0]
  swivel:
    rotates_about: z
    letter: C
    invert: false
    range_deg: [-360000.0, 360000.0]
```

Recipe specifies a fixed orientation:

```yaml
print_orientation:
  kind: fixed
  tilt_deg: 30.0
  swivel_deg: 45.0
```

**Slicer flow for a part-frame vertex `(x_p, y_p, z_p) = (10, 0, 5)`:**

1. Recipe → canonical joints: `JointAngles(tilt_rad=π/6, swivel_rad=π/4)`.
2. Profile says `tilt.rotates_about="x"`, `swivel.rotates_about="z"`. So the
   chain applies `R_x(π/6) · R_z(π/4) · (10, 0, 5)`.
3. `R_z(π/4) · (10, 0, 5) = (10·cos(π/4), 10·sin(π/4), 5) ≈ (7.071, 7.071, 5)`.
4. `R_x(π/6) · (7.071, 7.071, 5) = (7.071, 7.071·cos(π/6) − 5·sin(π/6),
   7.071·sin(π/6) + 5·cos(π/6)) = (7.071, 6.124 − 2.5, 3.536 + 4.330) ≈
   (7.071, 3.624, 7.866)`.
5. Postprocessor reads `tilt.letter="A"`, `swivel.letter="C"`, neither
   inverted. Emits:
   ```
   G1 X7.0711 Y3.6237 Z7.8657 A30 C45 E… F…
   ```

## 3. Worked example: B+C profile (Open5X Voron)

`open5x_voron.yaml`:

```yaml
kinematic_chain:
  kind: tilt_swivel
  tilt:
    rotates_about: y     # <-- different physical axis
    letter: B            # <-- different G-code letter
    invert: false
    range_deg: [-110.0, 110.0]
  swivel:
    rotates_about: z
    letter: C
    invert: false
    range_deg: [-360000.0, 360000.0]
```

**Same recipe** (`tilt_deg=30, swivel_deg=45`), **same part-frame vertex**
`(10, 0, 5)`:

1. Canonical joints: `JointAngles(tilt_rad=π/6, swivel_rad=π/4)`.
2. Profile says `tilt.rotates_about="y"` now. So the chain applies
   `R_y(π/6) · R_z(π/4) · (10, 0, 5)`.
3. `R_z(π/4) · (10, 0, 5) ≈ (7.071, 7.071, 5)`.
4. `R_y(π/6) · (7.071, 7.071, 5) = (7.071·cos(π/6) + 5·sin(π/6), 7.071,
   −7.071·sin(π/6) + 5·cos(π/6)) = (6.124 + 2.5, 7.071, −3.536 + 4.330) ≈
   (8.624, 7.071, 0.795)`.
5. Postprocessor reads `tilt.letter="B"`. Emits:
   ```
   G1 X8.6237 Y7.0711 Z0.7946 B30 C45 E… F…
   ```

**Note:** the *machine-frame* coordinates differ between A+C and B+C, because
the physical tilt axes are different. That is *correct* — a Voron and a
Prusa are not the same machine. The point of the abstraction is that the
*recipe* and *kinematics math* are identical; only the profile differs.

## 4. The `invert` flag

If the hardware's positive-rotation direction is mirrored from the right-hand-
rule assumption (which is *inferred*, not verified — see `OPEN5X_NOTES.md`
§2), flip `invert: true` on the affected axis. The kinematic transform is
unchanged. The postprocessor negates the canonical angle just before
formatting:

```python
def _axis_token(axis_spec, canonical_rad):
    deg = math.degrees(canonical_rad)
    if axis_spec.invert:
        deg = -deg
    return f"{axis_spec.letter}{format(deg)}"
```

Concretely: with `invert: true` on the tilt axis and the example above,
the A token becomes `A-30` while X/Y/Z/C are byte-identical. Tests
(`test_kinematics.py::test_invert_flag_flips_only_axis_signs`) assert this
exact property.

## 5. Singularity at A ≈ 0

The smooth-through interpolation lives in
`bioslice5x/kinematics/singularity.py`. Per ARCHITECTURE.md §7 item 2:

- Detection threshold: `|tilt| < 2°` (configurable per call).
- Action: linearly interpolate `swivel` across each contiguous in-band span,
  from the last out-of-band swivel before the span to the first out-of-band
  swivel after. Tilt is unchanged.
- Warning: `RuntimeWarning` emitted per span, naming the affected sample
  range and entry/exit swivel.

Phase 2b's fixed-orientation recipe doesn't exercise this — every move has
the same joints, so a print at `tilt_deg=0` produces a constant in-band run
that interpolates to itself (no-op). The unit tests construct synthetic
varying-joint sequences directly. Phase 2c, when joints vary per layer,
will exercise this for real.

## 6. Sanity-check by inspection for a Voron contributor

1. Open `src/bioslice5x/profile/library/open5x_voron.yaml`. Verify your
   physical machine matches: tilt rotates about Y (the carriage Y, not the
   bed Y — *machine* Y), swivel rotates about Z.
2. If your tilt direction is right-hand-rule about +Y, leave `invert: false`.
   If it's the opposite, set `invert: true` and re-slice — only the B
   token's sign flips in the G-code.
3. Run `bioslice5x dry-run` with a short recipe; verify the first few B/C
   commands match what your hardware does when you drive each axis manually.
4. If your build volume differs, update `build_volume` and `range_deg` per
   your `M208` in the Duet firmware.

No kinematics code edits at any step.
