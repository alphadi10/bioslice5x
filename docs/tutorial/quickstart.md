# Quickstart: from `git clone` to your first G-code

This walkthrough takes a fresh checkout and produces RepRapFirmware G-code
for a 10 mm cube using collagen-I on the hypothetical 3-axis profile.
About 10 minutes start to finish.

## 0. Prerequisites

- Python 3.11+. Earlier Pythons can't emit G-code (see
  `CONTRIBUTING.md`).
- [`uv`](https://docs.astral.sh/uv/) for dependency management.

## 1. Clone and install

```bash
git clone https://github.com/bioslice5x/bioslice5x
cd bioslice5x
uv sync --all-extras --dev
```

`uv sync` installs the package in editable mode plus all dev tooling
(pytest, ruff, mypy, import-linter).

## 2. Verify the install

```bash
uv run pytest -x
uv run ruff check
uv run mypy
```

Every check should pass. If pytest reports skipped tests on Python <
3.11, that's the expected behaviour — emit_rrf needs `datetime.UTC`.

## 3. Generate a sample mesh

The repo ships sample meshes via a procedural generator:

```bash
uv run python samples/generate_samples.py
ls samples/
# cube_10mm.stl
# cylinder_5mm_radius_10mm_tall.stl
```

## 4. Inspect the shipped recipes

```bash
cat samples/cube_collagen_recipe.yaml
```

```yaml
name: cube_collagen_demo
syringes:
  - id: 0
    bioink: collagen_i_8mg_per_mL
    cell_payload: general_mammalian
    needle:
      inner_diameter_mm: 0.84
      length_mm: 12.7
      gauge_label: "18G"
slicing:
  layer_height_mm: 0.4
  line_width_mm: 0.5
  print_speed_mm_per_min: 60.0
  infill_density: 0.2          # 20% rectilinear infill (ADR-002)
```

## 5. Slice

```bash
uv run bioslice5x slice samples/cube_10mm.stl \
    --profile hypothetical_3axis \
    --recipe samples/cube_collagen_recipe.yaml \
    --output out.gcode
```

You should see:

```
bioslice5x: wrote out.gcode (N moves, max wall shear X.X Pa)
```

## 6. Inspect the output

```bash
head -50 out.gcode
```

The header includes:

- Generation timestamp
- Profile and recipe names
- Bioink + cell metadata with calibration status
- Per-syringe maximum computed wall shear stress and threshold
- The `;META:` machine-readable block

The header should declare:

```
;META: bioink_calibration=uncalibrated
;META: cells_calibration=uncalibrated
;META: bath_calibration=none
;META: shear_model=newtonian_conservative
;META: extrusion_mode=displacement
;META: kinematic_chain=three_axis
;META: firmware=rrf
;META: safety_override=false
;META: syringe_count=1
```

Body is a sequence of G1 lines moving X, Y, Z, with E values in plunger
millimeters (relative, `M83` mode).

## 7. Try a conformal print

```bash
uv run bioslice5x slice samples/cylinder_5mm_radius_10mm_tall.stl \
    --profile open5x_prusa \
    --recipe samples/cylinder_conformal_recipe.yaml \
    --output cylinder_out.gcode
```

The cylinder recipe specifies `mode: wrap_around_axis` with
`wrap_axis: z`. The G-code includes A and C tokens on every G1 line
(A=0, C sweeping through θ).

## 8. Hardware commissioning (5-axis only)

Before printing on a physical 5-axis machine, verify the right-hand-rule
sign on each rotary axis. BioSlice5X provides a dry-run mode that emits
just the first few moves:

```bash
uv run bioslice5x dry-run samples/cylinder_5mm_radius_10mm_tall.stl \
    --profile open5x_prusa \
    --recipe samples/cylinder_conformal_recipe.yaml \
    --moves 6 \
    --output commissioning.gcode
```

Drive each move manually and confirm the rotation direction matches the
commanded sign. If inverted, set `invert: true` on the affected axis in
the profile YAML — no code changes required. See
[`docs/OPEN5X_NOTES.md`](../OPEN5X_NOTES.md) §2 for the full
commissioning procedure.

## What to read next

- [`ARCHITECTURE.md`](../../ARCHITECTURE.md) — how the slicer is organised.
- [`docs/PHASE_2B_NOTES.md`](../PHASE_2B_NOTES.md) — kinematic conventions
  with worked examples.
- [`LIMITATIONS.md`](../../LIMITATIONS.md) — what v0.1.0 doesn't do.
- [`docs/adr/`](../adr/) — design decisions.
