"""Cell-viability validation pass.

Walks every extrusion move, computes Newtonian wall shear stress from the
move's flow rate and the syringe's needle + bioink, and raises
CellViabilityError on the first segment that exceeds the configured limit.
Travel moves and zero-flow segments are skipped.

Per ARCHITECTURE.md §4.3, this runs *between* path generation and G-code
emission. The G-code emitter does not run when this raises (unless the
caller explicitly opts into a tagged-override output via `force=True`).
"""

from __future__ import annotations

from dataclasses import dataclass

from bioslice5x.errors import CellViabilityError
from bioslice5x.extruder.shear import newtonian_wall_shear_stress_pa
from bioslice5x.extruder.syringe import DisplacementSyringe
from bioslice5x.pathing.types import Move


@dataclass(frozen=True)
class SegmentStress:
    """Computed stress for a single move — for the cell-stress report."""

    segment_id: str
    syringe_id: int
    flow_rate_uL_per_s: float
    wall_shear_stress_pa: float
    threshold_pa: float


@dataclass(frozen=True)
class StressReport:
    """Per-syringe summary of computed shear-stress across the path.

    `violations` is non-empty only when validation ran with `force=True` and
    one or more segments exceeded their syringe's threshold. Used by the
    G-code emitter to populate the SAFETY_OVERRIDE warning block.
    """

    per_segment: tuple[SegmentStress, ...]
    max_by_syringe: dict[int, float]
    threshold_by_syringe: dict[int, float]
    violations: tuple[SegmentStress, ...] = ()

    def max_observed_pa(self) -> float:
        return max(self.max_by_syringe.values(), default=0.0)


def validate_path(
    moves: list[Move],
    syringes_by_id: dict[int, DisplacementSyringe],
    *,
    force: bool = False,
) -> StressReport:
    """Compute per-segment shear and raise CellViabilityError on violation.

    If `force=True`, violations are recorded in the report but not raised;
    used only by the CLI's `--force` development flag.
    """
    per_segment: list[SegmentStress] = []
    violations: list[SegmentStress] = []
    max_by_syringe: dict[int, float] = dict.fromkeys(syringes_by_id, 0.0)
    threshold_by_syringe = {
        sid: syr.cell_payload.max_wall_shear_stress_pa for sid, syr in syringes_by_id.items()
    }

    for move in moves:
        if move.is_travel or move.extrusion_volume_uL <= 0:
            continue
        syringe = syringes_by_id.get(move.syringe_id)
        if syringe is None:
            raise CellViabilityError(
                segment_id=move.segment_id,
                computed_wall_shear_pa=0.0,
                threshold_pa=0.0,
                bioink_name="<unknown>",
                cell_type="<unknown>",
                remediation=f"move references unknown syringe id {move.syringe_id}",
            )
        bulk_mu = syringe.bioink.rheology.bulk_viscosity_pa_s()
        stress = newtonian_wall_shear_stress_pa(
            flow_rate_uL_per_s=move.flow_rate_uL_per_s,
            needle_inner_diameter_mm=syringe.needle.inner_diameter_mm,
            bulk_viscosity_pa_s=bulk_mu,
        )
        threshold = syringe.cell_payload.max_wall_shear_stress_pa
        segment_stress = SegmentStress(
            segment_id=move.segment_id,
            syringe_id=syringe.syringe_id,
            flow_rate_uL_per_s=move.flow_rate_uL_per_s,
            wall_shear_stress_pa=stress,
            threshold_pa=threshold,
        )
        per_segment.append(segment_stress)
        if stress > max_by_syringe[syringe.syringe_id]:
            max_by_syringe[syringe.syringe_id] = stress
        if stress > threshold:
            if not force:
                raise CellViabilityError(
                    segment_id=move.segment_id,
                    computed_wall_shear_pa=stress,
                    threshold_pa=threshold,
                    bioink_name=syringe.bioink.name,
                    cell_type=syringe.cell_payload.cell_type,
                    remediation="lower print_speed_mm_per_min or use a larger needle gauge",
                )
            violations.append(segment_stress)

    return StressReport(
        per_segment=tuple(per_segment),
        max_by_syringe=max_by_syringe,
        threshold_by_syringe=threshold_by_syringe,
        violations=tuple(violations),
    )


__all__ = ["SegmentStress", "StressReport", "validate_path"]
