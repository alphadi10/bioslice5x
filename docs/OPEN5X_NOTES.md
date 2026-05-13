# Open5X — Reference Notes for BioSlice5X

This document captures the hardware/firmware facts of the Open5X project (https://github.com/FreddieHong19/Open5x) that bear on the design of BioSlice5X's kinematics module and G-code post-processor. Every claim is cited to a file path in the repo. Open5X is MIT-licensed, so direct convention reuse is fine.

## 1. Repository Overview

Open5X is an open-source kit that upgrades a popular off-the-shelf 3-axis FDM printer to 5-axis additive manufacturing by adding a two-DOF rotary platform under the nozzle. It originated as a Prusa i3 MK3s conversion at Imperial College and was first published at CHI 2022 (DOI 10.1145/3491101.3519782) and Additive Manufacturing 2023 (DOI 10.1016/j.addma.2023.103546), per `README.md`. The repo now hosts mechanical variants — Prusa i3, E3D Toolchanger, Voron 0, and a Jubilee toolchanger fork — alongside one shared Duet2 firmware configuration and a Grasshopper-based slicer.

Top-level layout:

- `Duet2_Configuration/` — RepRapFirmware config for the canonical Prusa i3 build (`sys/config.g`, `sys/home*.g`, macros, web UI bundle, a `Version_Save/` snapshot from 2021).
- `3D_Model/` — STL/STEP parts for each chassis variant. Voron_0 and Jubilee variants ship their own `DuetConfig`/`System files` trees with chassis-specific configs.
- `Grasshopper_Definition/` — three `.gh` slicer files and two Rhino `.3dm` machine-model files for collision simulation.
- `LICENSE` (MIT), `README.md`.

No sample `.gcode` is checked into the repo; the slicer emits G-code at runtime in Grasshopper. This is a real gap for downstream tooling and one BioSlice5X should plug by shipping golden-sample G-code files.

## 2. Kinematic Configuration

**Both rotaries are on the bed; the toolhead remains a stock 3-axis nozzle.** This matches BioSlice5X's "tilt-the-bed, not tilt-the-nozzle" requirement. The carriage replaces the stock Y-axis bed: the former Y-bed becomes a "rotary gantry" carrying a tilt yoke and a slewing-ring rotary plate.

### Naming convention (canonical for BioSlice5X)

Open5X's axis letter naming is **inconsistent across chassis variants** — this is the single biggest source of confusion when reading the repo. The actual *physical* convention is unchanged across variants; only the G-code letters differ.

| Chassis variant | Tilt letter | Plate letter | Rotates about | Source |
|---|---|---|---|---|
| Prusa, Version_Save (2021) | **A** | **C** | A about X, C about Z | `Duet2_Configuration/Version_Save/210809_config.txt` |
| Prusa, current `sys/config.g` | U | V | (same physical axes; relabelled) | `Duet2_Configuration/sys/config.g` |
| Jubilee Toolchanger | B | C | B about Y, C about Z | `3D_Model/Jubilee Tool changer/README.md` |
| Voron 0 | B | C | B about Y, C about Z | `3D_Model/Voron_0/DuetConfig/sys/config.g` |

**BioSlice5X ships one profile per documented chassis variant in `src/bioslice5x/profile/library/`:**

| Profile YAML | Chassis | Tilt letter / axis | Swivel letter / axis | Tilt range |
|---|---|---|---|---|
| `open5x_prusa.yaml` (default) | Prusa i3, Version_Save 2021 firmware | A / world X | C / world Z | ±200° |
| `open5x_prusa_uv.yaml` | Prusa i3, current upstream firmware (M584 U+V) | U / world X | V / world Z | ±200° |
| `open5x_voron.yaml` | Voron 0 conversion | B / world Y | C / world Z | ±110° |
| `open5x_jubilee.yaml` | Jubilee Toolchanger conversion | B / world Y | C / world Z | ±200° |
| `hypothetical_3axis.yaml` | Bench-test, no rotaries | — | — | — |

All five profiles share the same canonical (tilt, swivel) kinematics math. The only thing that varies is the post-processor's letter mapping (`tilt.letter` / `swivel.letter` in YAML) and the per-axis range. Adding a new chassis is a YAML file, not a code change.

The default `open5x_prusa` follows the Prusa Version_Save (2021) and ISO 841:
- **A axis** — tilt, rotates about world **X**, right-hand rule (positive A → bed-top rotates from +Z toward +Y).
- **C axis** — plate, rotates about world **Z**, right-hand rule (positive C → +X-direction of plate rotates toward +Y).
- Zero pose: A = 0 → plate normal is +Z (bed horizontal). C = 0 → an operator-chosen mechanical mark on the plate aligns with +X.

The Jubilee README is the most explicit text in the Open5X repo about axis-letter conventions and states: *"A axis would rotate around the X-axis by convention; B axis rotates around the Y-axis by convention; C axis rotates around the Z-axis by convention"* (`3D_Model/Jubilee Tool changer/README.md`). This is consistent with ISO 841: the Jubilee chassis tilts about Y, so its profile uses B + C; the Prusa tilts about X, so its profile uses A + C.

> **Before printing on any freshly built or freshly reflashed machine**: load
> `samples/commissioning_rotary_sign_check.gcode` and watch the bed. The
> sequence emits ±15° tilt and ±30° swivel moves at low feed; if either
> axis rotates the opposite direction from the right-hand-rule expectation,
> flip the `invert` flag on the affected axis in your active profile YAML.
> No kinematics code change is required — `invert` is a postprocessor flag.
> The cost of getting this wrong on a cell-laden print is destroyed payload;
> the cost of the commissioning check is one minute of bed motion.

### RRF kinematic declaration

The shipping `Duet2_Configuration/sys/config.g` declares:
```
M669 K0 X1:0:0:0:0 Y0:-1:0:0:0 Z0:0:1:0:0 U0:0:0:1:0 V0:0:0:0:1
```
K0 selects Cartesian kinematics; the five 5-component vectors are the end-effector contribution of each motor axis (RRF's "matrix" mode). With this matrix, the rotary axes appear to RRF as **independent linear axes**. Motion planning treats them as decoupled generalized coordinates; any rotary-Cartesian coupling correction is done **upstream in the slicer**. BioSlice5X inherits this responsibility — the post-processor must emit pre-decoupled X, Y, Z, A, C values, since the firmware will not perform forward kinematics.

### Sign convention caveat

> ⚠️ **VERIFY AT COMMISSIONING — right-hand-rule sign is inferred, not confirmed.**
>
> Open5X never explicitly documents right-hand rule in plain text. The Prusa config comments say *"Drive 4 goes anti-clockwise: U Axis"* and *"Drive 5 goes anti-clockwise: V Axis"* (`Duet2_Configuration/sys/config.g`), implying a positive command rotates anti-clockwise when viewed along the positive axis — consistent with the right-hand rule. We adopt right-hand rule as the working assumption for both A and C.
>
> Before printing any biological payload on a freshly built machine, the operator MUST run BioSlice5X's `bioslice5x dry-run` mode, which emits the first N moves of a print to a sidecar file. Drive each move manually and confirm physical rotation direction matches the commanded angle's sign. If sign is inverted on either axis, set `tilt_invert: true` or `swivel_invert: true` in the machine profile YAML — this is a one-line fix that does not require changing the kinematics math.
>
> Cost of getting this wrong on a cell-laden print: the part is mirrored about the relevant plane, the path collides with previously-deposited geometry, the bath kerf opens against the deposition direction, and ~$200–$2000 of cell payload is destroyed. The commissioning check is cheap; the failure mode is expensive.

## 3. Build Volume & Axis Limits

From `Duet2_Configuration/sys/config.g`:
```
M208 X-126:125  Y-92.3:50  Z125:-1  A-200:200  B-12000:12000
```
The comment "*centre of the rotating bed is set to origin 0,0*" on the same line clarifies that XY are centred on the rotary plate. The A and B labels on this M208 line are stale from Version_Save; on the current config they apply to U and V respectively. Effective limits:

- **Linear**: X ∈ [-126, 125] mm, Y ∈ [-92.3, 50] mm, Z ∈ [-1, 125] mm.
- **Tilt** (Prusa): ±200° (intentionally over half a revolution).
- **Plate** (Prusa): ±12 000° — effectively unbounded; the C axis can keep winding because nothing on the slewing ring is wired to it.
- **Tilt** (Voron): ±110° — much tighter; treat this as the conservative default for unfamiliar hardware.

`M564 H0` is set in every config: **unhomed movement is allowed**, which is how the rotaries are usable without endstops.

Feed rates and motion limits, canonical Prusa (`Duet2_Configuration/sys/config.g`):
```
M203 X12000 Y12000 Z750 E1500 A5000  B12000   ; max speeds (mm/min, deg/min)
M201 X1000  Y1000  Z1000 E1000 A1000  B1000   ; accelerations
M566 X480   Y480   Z24   E270  A480   B480 P1 ; max instantaneous jerk
M92  X100   Y100   Z400  E280  A26.667 B35.556 ; steps per mm / per degree
M906 X620   Y620   Z560  E700  A1300  B1300 I10 ; motor currents (mA)
```

Where the M584-line maps A↔drive 4 (tilt) and B↔drive 5 (plate) in the current config. Translating to BioSlice5X letters:

- **A (tilt)** max 5 000 °/min ≈ 83 °/s; calibration 26.667 steps/° on the Prusa hardware (NEMA17 0.9° × 16 microsteps × 3:1 belt reduction).
- **C (plate)** max 12 000 °/min ≈ 200 °/s; calibration 35.556 steps/°.

For bioprinting, both rates are *much* higher than we'd ever want to use — bath drag and cell-safety limits will dominate well below these mechanical maxima. The values above are useful as upper sanity bounds in the kinematics module's profile validation.

Voron values for comparison: `M203 B61200 C61200` (1020 °/s peak — faster pulley ratio).

## 4. G-code Dialect (RRF specifics)

Firmware target: **RepRapFirmware on Duet 2 WiFi/Ethernet with a Duex5 expansion** (for drives 4 and 5). The canonical config targets a v3.3-era RRF; Voron config targets RRF 3.1.4 on a Duet 3 Mini; Jubilee targets RRF 3.2-beta on Duet 3.

Per `Duet2_Configuration/sys/config.g`:

- `G90` — absolute positioning for all linear and rotary axes.
- `M83` — relative extrusion (E in G1 is a delta, not absolute). BioSlice5X will likely keep this convention for the displacement-driven syringe E axis, since it composes naturally with multi-syringe tool changes.
- `M555 P2` — Marlin-style response emulation, harmless to keep.
- **Movement syntax**: `G1 X… Y… Z… A… C… E… F…`, all on one line. Rotary axes are passed in **absolute degrees**. Because of `M564 H0` the rotaries may be commanded without homing. No mode switch is needed between linear and rotary moves.
- **No custom M5xx-range macros** are introduced by Open5X. M581 wires a filament-runout sensor to `trigger2.g`. BioSlice5X is free to claim the M5xx range for syringe-specific controls (e.g., pneumatic pressure setpoint) without colliding with Open5X.
- **Tool change**: a single tool is defined (`M563 P0 D0 H1 F0`). `tpre0.g`, `tpost0.g`, `tfree0.g` are empty bodies. Multi-syringe BioSlice5X will author these from scratch — the Jubilee variant has stubs for 4 tools but no real content.

### Sample G-code line shape (synthesised — repo has no checked-in samples)

```
G1 X12.34 Y-5.67 Z2.10 A37.5 C-180.0 E0.0421 F900
```

Token order to emit: `X Y Z A C E F`. This mirrors the M584 column order in the canonical config and is consistent with how RRF parses G1.

## 5. Homing & Startup Sequence

From `Duet2_Configuration/sys/homeall.g`:

1. Loosen XY motor current to 50 % (`M913 X50 Y50 Z100`) and relax stallguard thresholds.
2. `G91; G1 Z8 F800 H2` — lift Z 8 mm before any XY motion.
3. `G1 H1 X-255 F4800; G1 H1 Y-215 F4800` — sensorless homing of X then Y via stallguard (`M574 X1 S3`, `M574 Y1 S3`).
4. `G1 H2 Z2 F2600` — small relative Z up.
5. `G90; G1 X30 Y30 F6000; G30` — move to a probe point and run G30 for Z-trigger height.
6. Restore motor currents and stallguard.

**There is no automatic homing of A or C.** The user manually drives the rotaries to the centred zero pose and calls `G92 A0 C0`. The Jubilee build adds explicit `homeb.g` and `homec.g` (in `3D_Model/Jubilee Tool changer/System files/sys/`) but they just call `G92 B0` / `G92 C0` and the file body warns *"no limit switches on B axis. Thus, need to manually level it."*

`bed.g` (Prusa) performs an automatic two-point Z probe (G30 at X25/Y100 and X220/Y100) to level the gantry — this is a regular FDM workflow that BioSlice5X does not need to inherit since the bioprinter has no heated bed and uses a clamped Petri-dish target.

**BioSlice5X startup-block requirement**: the emitter must produce a header that includes `G90`, `G92 A0 C0` (after operator confirms manual mechanical zero), and an XYZ home. The operator-zero step must be called out explicitly in the generated G-code's comment header for traceability.

## 6. Slicer Architecture (Grasshopper-based)

From `Grasshopper_Definition/README.md` and the linked CHI/AM papers:

The slicer is a Grasshopper definition running inside Rhino 3D. The user imports a mesh, selects the surface to print conformally onto, and the script generates a conformal toolpath (perimeters and infill drawn as B-splines along the substrate surface), simulates motion against a 3D model of the rotary gantry (loaded from `Prusa_5axis_profile_v2.3dm`), and emits G-code — all in one environment.

Slicing parameters exposed in the GUI: nozzle size, layer height, travel height, infill pattern direction, number of perimeter passes. Dependencies: Heteroptera (for centroid computation) and `System.Linq`. The repo maintainer flags that migration off Rhino *"somewhere free and open source"* is the eventual goal — **this is the gap BioSlice5X plugs.**

Three slicer variants shipped:
- `open5x_supportless_slicing_ver2.gh` — supportless conformal slicing on arbitrary surfaces.
- `2022_03_22_open5x_supportless_surface_Lite.gh` — preview variant.
- `Open5x_Gcode_0503.gh` — pure G-code emitter.

The `.gh` files are binary and not directly parseable; the algorithm details are best gleaned from the CHI 2022 paper (arxiv 2202.11426). The key reusable concept is the **decomposition: geometry → conformal toolpath → rotary-gantry kinematic transform → G-code**, with collision simulation as a separate, swappable downstream stage.

## 7. Reusable Conventions for BioSlice5X

Concrete carry-overs:

- **Two rotaries on the bed**, three Cartesian DOFs on the nozzle. Forward kinematic from machine frame to part frame is `T_part = R_C(c) · R_A(a) · T_xyz` where `R_A` is rotation about world X (tilt) and `R_C` is rotation about world Z (plate), both right-hand rule.
- **Emit G-code with absolute A and C on every G1 line.** Do not wrap C — the slewing ring is mechanically unbounded and unwinding is expected across layers.
- **Default soft limits**: tilt ±110° (Voron-conservative), plate ±360 000° (effectively unbounded). Make both per-profile parameters.
- **Startup block** mirrors Open5X: `G90`, syringe-appropriate extrusion mode, XYZ home, explicit `G92 A0 C0` after operator confirmation.
- **Asymmetric speed envelope**: A is roughly an order of magnitude slower than C. Cap commanded A-axis feed at ≈5 000 °/min for Prusa-class hardware; expose as a profile parameter.
- **Decoupled architecture**: kinematic transform module and G-code emitter are separate. The emitter takes pre-transformed (x, y, z, a, c) tuples plus extrusion deltas and produces text. The transform module is unit-testable in isolation. Visualization is a third, downstream-only consumer.
- **No heated bed.** Replace M140 with M140 H-1 disabled. Budget for clamping fixtures that survive ≥45° tilt and keep the support bath from sloshing.

## 8. Open Questions

- **Sign convention** is not documented explicitly. *"Anti-clockwise"* comments in M569 lines suggest right-hand rule, but this needs hardware verification on first commissioning.
- **Zero-pose definition for A and C is implicit only.** Because there is no homing, "0, 0" means "wherever the operator G92'd it to." BioSlice5X workflow must require an explicit manual-zero step with operator confirmation in the generated G-code header.
- **No checked-in sample G-code in Open5X.** The token-order assumption (`X Y Z A C E F`) is inferred from the M584 column ordering. Verify by running the Grasshopper definition once and capturing its output, or by asking the maintainer.
- **Build volume is asymmetric and chassis-dependent.** The Prusa values are for a 70 mm-diameter print bed (`3D_Model/Prusa i3/Printbed_70mm v3.stl`); Voron and Jubilee builds differ. Parameterise the envelope per profile.
- **The Grasshopper slicer's collision model** is locked in binary `.gh` files. Re-deriving the rotary-gantry sweep volume requires either the STEP assembly (`3D_Model/E3D_ToolChanger/ToolChanger-Open5x-assembly.step`) or a one-time trace of the slicer's output in a Rhino trial.
- **Tool-change semantics for multi-syringe** are not defined in the upstream repo. The Jubilee variant has empty stubs for tools 0–3. BioSlice5X will need to author these from scratch — purge volumes, retract-clear paths through bath, dwell-for-crosslinking semantics.

---

**References:**
- [Open5X repository root](https://github.com/FreddieHong19/Open5x)
- [Open5x/Duet2_Configuration tree](https://github.com/FreddieHong19/Open5x/tree/main/Duet2_Configuration)
- [Open5x/Grasshopper_Definition README](https://github.com/FreddieHong19/Open5x/blob/main/Grasshopper_Definition/README.md)
- [Open5x/3D_Model/Jubilee Tool changer/README.md](https://github.com/FreddieHong19/Open5x/blob/main/3D_Model/Jubilee%20Tool%20changer/README.md)
- [Open5x: Accessible 5-axis 3D printing and conformal slicing (arxiv 2202.11426)](https://arxiv.org/abs/2202.11426)
- [Open5x: ACM CHI 2022 paper](https://dl.acm.org/doi/10.1145/3491101.3519782)
