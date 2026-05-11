"""Top-level Slicer — the public library API.

```python
from bioslice5x import Slicer, load_profile, load_recipe, load_mesh

slicer = Slicer(profile=load_profile("hypothetical_3axis"), recipe=load_recipe("r.yaml"))
result = slicer.slice(load_mesh("model.stl"))
result.write_gcode("out.gcode")
```

The CLI is a thin shim over this — every CLI verb maps 1:1 to a method here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import trimesh

from bioslice5x.bioink.loader import load_default_library
from bioslice5x.errors import ProfileValidationError
from bioslice5x.extruder.syringe import DisplacementSyringe
from bioslice5x.extruder.validate import StressReport, validate_path
from bioslice5x.geometry.conformal_slicer import wrap_around_axis_slice
from bioslice5x.geometry.flat_slicer import flat_slice
from bioslice5x.kinematics.chain import (
    KinematicChain,
    kinematic_chain_from_profile,
)
from bioslice5x.pathing.conformal_perimeter import generate_conformal_perimeter_paths
from bioslice5x.pathing.infill import flat_lift_factory, generate_infill_moves
from bioslice5x.pathing.perimeter import generate_perimeter_paths
from bioslice5x.pathing.types import Move
from bioslice5x.postprocessor.rrf import emit_rrf
from bioslice5x.profile.models import MachineProfile
from bioslice5x.recipe.models import (
    FlatSlicing,
    Recipe,
    Syringe,
    WrapAroundAxisSlicing,
)
from bioslice5x.recipe.orientation import orientation_provider_from_recipe


@dataclass(frozen=True)
class SliceResult:
    """Result of `Slicer.slice(mesh)`.

    Carries the G-code text plus the structured cell-stress report and
    per-syringe extrusion totals. `dry_run(n_moves)` produces a sidecar
    G-code file containing only the first `n_moves` G1 lines — used for
    hardware commissioning (right-hand-rule sign verification).
    """

    moves: tuple[Move, ...]
    gcode: str
    stress_report: StressReport
    total_bioink_uL_by_syringe: dict[int, float]
    estimated_seconds: float

    def write_gcode(self, path: str | Path) -> None:
        Path(path).write_text(self.gcode, encoding="utf-8")

    def dry_run(self, n_moves: int) -> str:
        """Return G-code containing only the first `n_moves` G1 lines.

        Header, startup, footer are preserved so the result is a valid file.
        Used for hardware commissioning: drive these few moves manually and
        verify that the rotation directions match the commanded signs.
        See `docs/OPEN5X_NOTES.md` §2.
        """
        if n_moves <= 0:
            raise ValueError(f"n_moves must be positive, got {n_moves}")
        out_lines: list[str] = []
        in_print = False
        emitted = 0
        for line in self.gcode.splitlines():
            if line == "; ---- start of print ----":
                in_print = True
                out_lines.append(line)
                continue
            if line == "; ---- end of print ----":
                out_lines.append(f"; (dry-run truncated to first {n_moves} moves)")
                out_lines.append(line)
                in_print = False
                continue
            if in_print and line.startswith("G1"):
                if emitted < n_moves:
                    out_lines.append(line)
                    emitted += 1
                continue
            out_lines.append(line)
        return "\n".join(out_lines) + "\n"


class Slicer:
    """Slice meshes into G-code per a given machine profile and recipe.

    The Slicer holds the profile + recipe + the bioink/cell library used
    to resolve names. Construction is cheap; the heavy lifting happens in
    `.slice(mesh)`.
    """

    def __init__(self, profile: MachineProfile, recipe: Recipe) -> None:
        self.profile = profile
        self.recipe = recipe
        self._bioinks, self._cells = load_default_library()
        self._syringes_by_id: dict[int, DisplacementSyringe] = {
            s.id: self._build_syringe(s) for s in recipe.syringes
        }

    def _build_syringe(self, syringe_spec: Syringe) -> DisplacementSyringe:
        if syringe_spec.bioink not in self._bioinks:
            raise ProfileValidationError(
                source=f"recipe.syringes[{syringe_spec.id}]",
                detail=(
                    f"bioink {syringe_spec.bioink!r} not in library; "
                    f"available: {sorted(self._bioinks)}"
                ),
            )
        if syringe_spec.cell_payload not in self._cells:
            raise ProfileValidationError(
                source=f"recipe.syringes[{syringe_spec.id}]",
                detail=(
                    f"cell_payload {syringe_spec.cell_payload!r} not in library; "
                    f"available: {sorted(self._cells)}"
                ),
            )
        bioink = self._bioinks[syringe_spec.bioink]
        if syringe_spec.temperature_setpoint_c is None:
            lo, hi = bioink.working_temperature_c
            temp = (lo + hi) / 2.0
        else:
            temp = syringe_spec.temperature_setpoint_c
        return DisplacementSyringe(
            syringe_id=syringe_spec.id,
            barrel_inner_diameter_mm=syringe_spec.barrel_inner_diameter_mm,
            total_volume_uL=syringe_spec.total_volume_uL,
            needle=syringe_spec.needle,
            bioink=bioink,
            cell_payload=self._cells[syringe_spec.cell_payload],
            temperature_setpoint_c=temp,
        )

    def slice(self, mesh: trimesh.Trimesh, *, force: bool = False) -> SliceResult:
        """Run the pipeline: slice → transform → paths → shear validation → G-code.

        Supports three_axis (Phase 2a), tilt_swivel (Phase 2b) chains, and
        flat or wrap-around-axis conformal slicing (Phase 2c). Multi-syringe
        (N>1) lands in Phase 2d.

        `force=True` records cell-viability violations in the stress report
        but does not raise. Reserved for the CLI's `--force` development flag.
        """
        for s in self.recipe.syringes:
            if s.region.kind != "all":
                raise NotImplementedError(
                    f"Phase 2d v0.1.0 supports Region(kind='all') only; got "
                    f"{s.region.kind!r}. bbox/submesh regions are a v0.1.1 deliverable."
                )

        chain = kinematic_chain_from_profile(self.profile)
        slicing_mode = self.recipe.slicing.mode

        # Per-syringe pass over the mesh. Naive ordering (syringe-id ascending);
        # smart cross-region travel minimization is a v0.1.1 optimization.
        moves: list[Move] = []
        for syringe in sorted(self.recipe.syringes, key=lambda s: s.id):
            if isinstance(slicing_mode, FlatSlicing):
                syr_moves = self._slice_flat(mesh, syringe, chain)
            elif isinstance(slicing_mode, WrapAroundAxisSlicing):
                syr_moves = self._slice_conformal(mesh, syringe, chain, slicing_mode)
            else:
                raise NotImplementedError(
                    f"unsupported slicing mode: {type(slicing_mode).__name__}"
                )
            moves.extend(syr_moves)
        stress_report = validate_path(moves, self._syringes_by_id, force=force)
        return self._finalize(moves, stress_report, force)

    def _slice_flat(
        self,
        mesh: trimesh.Trimesh,
        syringe: Syringe,
        chain: KinematicChain,
    ) -> list[Move]:
        from bioslice5x.kinematics.canonical import JointAngles  # local — see rrf.py

        layers = flat_slice(mesh, layer_height_mm=self.recipe.slicing.layer_height_mm)
        # Flat slicing uses one orientation per print (provider's layer 0).
        # Per-layer orientation against flat slices is well-defined but the
        # 2c v1 demo doesn't exercise it; 2c.1 will. For 3-axis chains, joints
        # stay None so the postprocessor skips A/C tokens.
        joints: JointAngles | None
        if self.profile.kinematic_chain.kind == "three_axis":
            joints = None
        else:
            provider = orientation_provider_from_recipe(self.recipe)
            joints = provider.joints_for_layer(0)
        moves = generate_perimeter_paths(
            layers=layers,
            syringe_id=syringe.id,
            slicing=self.recipe.slicing,
            kinematic_chain=chain,
            joints=joints,
        )
        # Infill — append rectilinear scan-line moves per layer. The same
        # `rectilinear_scan_segments` generator is the conformal-infill
        # entry point too; only the lift function changes. Per ADR-002.
        if self.recipe.slicing.infill_density > 0:
            current = moves[-1].end if moves else None
            for idx, layer in enumerate(layers):
                lift = flat_lift_factory(z=layer.z, joints=joints)
                start = current if current is not None else lift((0.0, 0.0))[0]
                infill_moves, current = generate_infill_moves(
                    list(layer.polygons),
                    syringe_id=syringe.id,
                    slicing=self.recipe.slicing,
                    layer_index=idx,
                    lift=lift,
                    start_point=start,
                )
                moves.extend(infill_moves)
        return moves

    def _slice_conformal(
        self,
        mesh: trimesh.Trimesh,
        syringe: Syringe,
        chain: KinematicChain,
        mode: WrapAroundAxisSlicing,
    ) -> list[Move]:
        if self.profile.kinematic_chain.kind == "three_axis":
            raise NotImplementedError(
                "wrap-around-axis slicing requires a tilt_swivel kinematic chain"
            )
        layers = wrap_around_axis_slice(
            mesh,
            mode,
            layer_height_mm=self.recipe.slicing.layer_height_mm,
            line_width_mm=self.recipe.slicing.line_width_mm,
            profile=self.profile,
        )
        return generate_conformal_perimeter_paths(
            layers=layers,
            syringe_id=syringe.id,
            slicing=self.recipe.slicing,
            kinematic_chain=chain,
            bath=self.recipe.bath,
        )

    def _finalize(self, moves: list[Move], stress_report: StressReport, force: bool) -> SliceResult:
        emitted = emit_rrf(
            moves=moves,
            profile=self.profile,
            recipe=self.recipe,
            syringes_by_id=self._syringes_by_id,
            stress_report=stress_report,
            force_override=force,
        )
        return SliceResult(
            moves=tuple(moves),
            gcode=emitted.text,
            stress_report=stress_report,
            total_bioink_uL_by_syringe=emitted.total_bioink_uL_by_syringe,
            estimated_seconds=emitted.estimated_seconds,
        )


__all__ = ["SliceResult", "Slicer"]
