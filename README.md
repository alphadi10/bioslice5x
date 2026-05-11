# BioSlice5X

**Open-source 5-axis slicer for syringe-based bioprinting.** Target
workflow: FRESH (Freeform Reversible Embedding of Suspended Hydrogels)
into a gelatin support bath, with multi-syringe coordinated deposition
and cell-viability-aware path validation.

**Status: v0.1.0.** Phase 1 → 2d shipped. Single-syringe and multi-
syringe (kind=all regions) flat and wrap-around-axis slicing produce
valid RepRapFirmware G-code for the Open5X Prusa and Voron profiles.

## Why this exists

Existing open-source 5-axis slicers (notably
[Open5X](https://github.com/FreddieHong19/Open5x)) target FDM thermoplastic
printing. Commercial bioprinting software (Cellink, Allevi, BIO INX) is
closed-source and 3-axis only. There is no open-source 5-axis slicer for
syringe bioprinting. BioSlice5X fills that gap.

## Quickstart

```bash
git clone https://github.com/bioslice5x/bioslice5x
cd bioslice5x
uv sync --all-extras --dev
uv run pytest

# Slice a sample cube on the hypothetical 3-axis profile:
uv run bioslice5x slice samples/cube_10mm.stl \
    --profile hypothetical_3axis \
    --recipe samples/cube_collagen_recipe.yaml \
    --output out.gcode
```

See [`docs/tutorial/quickstart.md`](docs/tutorial/quickstart.md) for the
full walkthrough.

## Hardware target

3-axis Cartesian XYZ + tilt and swivel rotaries on the build platform,
matching Open5X's kinematic family. v0.1.0 ships two real machine profiles:

- **`open5x_prusa`** — A about X, C about Z. Tilt range ±200°.
- **`open5x_voron`** — B about Y, C about Z. Tilt range ±110°.

Adding a new machine profile is a YAML file in
`src/bioslice5x/profile/library/`; no code changes required for the same
kinematic family. See [`docs/PHASE_2B_NOTES.md`](docs/PHASE_2B_NOTES.md)
for the worked examples and
[`docs/OPEN5X_NOTES.md`](docs/OPEN5X_NOTES.md) for the upstream-reference
conventions.

RepRapFirmware (Duet 2/3) G-code dialect. Marlin support is a v0.2.0+
deliverable.

## Key design properties

- **Cell viability is a hard constraint.** The slicer refuses to emit
  G-code that violates configured per-bioink shear-stress thresholds.
  See [ADR rationale](docs/BIOPRINTING_REQUIREMENTS.md).
- **Calibration provenance everywhere.** Every empirical parameter
  (bioink rheology, cell-shear thresholds, bath drag multipliers)
  carries a `calibrated_against` field. The G-code header surfaces
  calibration status via a `;META:` block.
- **General-form code paths from day one.** Recipe regions, kinematic
  chains, slicing modes, print orientation, and bath models all
  dispatch by `kind`; new variants are siblings, never special-case
  code paths.
- **ADRs for user-visible decisions.** Behaviour decisions with
  multiple plausible alternatives get an ADR before implementation.
  See [`docs/adr/`](docs/adr/).
- **Doctest-locked worked examples.** Every numerical example in the
  docs is pinned by a test that re-derives the value. Prose drifts;
  doctests don't.

## Documentation

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — module layout, data flow, design
  decisions.
- [`docs/OPEN5X_NOTES.md`](docs/OPEN5X_NOTES.md) — Open5X hardware/firmware
  reference notes.
- [`docs/BIOPRINTING_REQUIREMENTS.md`](docs/BIOPRINTING_REQUIREMENTS.md) —
  FRESH/CHIPS biological constraints translated to engineering requirements.
- [`docs/PHASE_2B_NOTES.md`](docs/PHASE_2B_NOTES.md) — canonical (tilt, swivel)
  → G-code letter mapping with A+C and B+C worked examples.
- [`docs/adr/README.md`](docs/adr/README.md) — Architecture Decision Records.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — dev setup, Python version policy,
  ADR threshold rule, golden-file regeneration.
- [`LIMITATIONS.md`](LIMITATIONS.md) — what v0.1.0 doesn't do.
- [`CHANGELOG.md`](CHANGELOG.md) — version history.

## Citation

If you use BioSlice5X in published research, please cite:

```
@software{bioslice5x,
  title = {BioSlice5X: open-source 5-axis slicer for syringe bioprinting},
  version = {0.1.0},
  year = {2026},
  url = {https://github.com/bioslice5x/bioslice5x},
}
```

## License

MIT — matching Open5X.

## Calibration disclaimer

All bioink rheology values, cell-shear thresholds, and bath drag
multipliers shipped in v0.1.0 are literature defaults flagged
`calibrated_against: "uncalibrated, literature default"`. Validate
against your own wet-lab data before relying on the slicer's
cell-viability check for publication-grade work. The G-code header
surfaces the calibration status on every emitted file.
