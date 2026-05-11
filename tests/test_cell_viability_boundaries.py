"""Boundary-case tests for the cell-viability check.

The cost of a missed cell-safety violation is roughly $200–$2000 of cell
payload destroyed and a lost experiment. Floating-point comparisons at
thresholds are a classic source of off-by-one and rounding bugs, so we
test the bracket explicitly: exactly-at-threshold, one-part-per-million
below, and one-part-per-million above.

The test constructs synthetic moves directly so the geometry is held
constant and only the flow rate (hence shear) varies. This isolates the
validation pass from any path-generation noise.
"""

from __future__ import annotations

import math

import pytest

from bioslice5x.bioink.models import Bioink, CellPayload, RheologicalModel
from bioslice5x.errors import CellViabilityError
from bioslice5x.extruder.shear import newtonian_wall_shear_stress_pa
from bioslice5x.extruder.syringe import DisplacementSyringe
from bioslice5x.extruder.validate import validate_path
from bioslice5x.pathing.types import Move, Point3D
from bioslice5x.recipe.models import Needle

# Test fixtures — pinned numerical envelope so the threshold arithmetic is
# transparent and reproducible.
NEEDLE_ID_MM = 0.26  # 25G
BULK_VISCOSITY_PA_S = 1.0
THRESHOLD_PA = 5000.0
MOVE_LENGTH_MM = 1.0
FEED_MM_PER_MIN = 600.0


def _q_uL_per_s_for_target_stress(target_pa: float) -> float:
    """Invert the Newtonian Poiseuille formula for the flow rate that
    produces exactly `target_pa` of wall shear stress.

    τ_w = 4·μ·Q / (π·r³)  ⇒  Q = τ_w · π · r³ / (4 · μ)
    Returns Q in µL/s (1 µL = 1e-9 m³).
    """
    r_m = (NEEDLE_ID_MM * 1e-3) / 2.0
    q_m3_per_s = target_pa * math.pi * (r_m**3) / (4.0 * BULK_VISCOSITY_PA_S)
    return q_m3_per_s * 1e9  # m³/s → µL/s


def _volume_uL_for_flow(flow_uL_per_s: float) -> float:
    """For a fixed move (1 mm at 600 mm/min = 0.1 s), what extrusion volume
    produces the given flow rate?

    flow = volume / time, with time = length/feed × 60.
    """
    time_s = (MOVE_LENGTH_MM / FEED_MM_PER_MIN) * 60.0
    return flow_uL_per_s * time_s


def _build_syringe() -> DisplacementSyringe:
    bioink = Bioink(
        name="test_newtonian_1Pas",
        density_g_per_mL=1.0,
        rheology=RheologicalModel(kind="newtonian", viscosity_pa_s=BULK_VISCOSITY_PA_S),
        working_temperature_c=(4.0, 37.0),
        crosslinking="none",
    )
    cells = CellPayload(
        name="test_cells",
        cell_type="test",
        cell_density_per_mL=1.0e6,
        max_wall_shear_stress_pa=THRESHOLD_PA,
    )
    return DisplacementSyringe(
        syringe_id=0,
        barrel_inner_diameter_mm=4.65,
        total_volume_uL=1000.0,
        needle=Needle(inner_diameter_mm=NEEDLE_ID_MM, length_mm=12.7),
        bioink=bioink,
        cell_payload=cells,
        temperature_setpoint_c=20.0,
    )


def _build_move(volume_uL: float) -> Move:
    return Move(
        start=Point3D(0.0, 0.0, 0.2),
        end=Point3D(MOVE_LENGTH_MM, 0.0, 0.2),
        syringe_id=0,
        is_travel=False,
        extrusion_volume_uL=volume_uL,
        feed_mm_per_min=FEED_MM_PER_MIN,
        segment_id="boundary_test",
    )


def test_shear_formula_inverse_round_trip() -> None:
    """The volume-for-target-stress helper is a true inverse of the shear formula."""
    target = THRESHOLD_PA
    q = _q_uL_per_s_for_target_stress(target)
    actual_stress = newtonian_wall_shear_stress_pa(
        flow_rate_uL_per_s=q,
        needle_inner_diameter_mm=NEEDLE_ID_MM,
        bulk_viscosity_pa_s=BULK_VISCOSITY_PA_S,
    )
    assert actual_stress == pytest.approx(target, rel=1e-12)


def test_boundary_exact_threshold_does_not_raise() -> None:
    """At exactly the threshold (τ == limit), the check passes.

    The implementation uses `stress > threshold` as the violation predicate,
    so equality is allowed by design. If this test starts failing, the
    predicate flipped to `>=` and we have a regression that turns
    operator-pinned thresholds into off-by-machine-epsilon errors.

    The float round-trip through (target → q → stress) introduces ~1e-12 Pa
    of error, so naively setting `threshold = TARGET` and computing `q` from
    TARGET would trip the violation predicate spuriously. Instead, we compute
    the stress that the formula produces from a chosen q and pin the
    threshold to that *exact* float — testing the predicate boundary without
    fighting floating-point noise.
    """
    q = _q_uL_per_s_for_target_stress(THRESHOLD_PA)
    move = _build_move(_volume_uL_for_flow(q))
    # The actual stress this move produces in the validator's float arithmetic:
    exact_stress = newtonian_wall_shear_stress_pa(
        flow_rate_uL_per_s=move.flow_rate_uL_per_s,
        needle_inner_diameter_mm=NEEDLE_ID_MM,
        bulk_viscosity_pa_s=BULK_VISCOSITY_PA_S,
    )
    # Pin the cell-payload threshold to that exact stress so the comparison
    # is `exact_stress > exact_stress` (False) — the predicate boundary.
    bioink = Bioink(
        name="test_newtonian_1Pas",
        density_g_per_mL=1.0,
        rheology=RheologicalModel(kind="newtonian", viscosity_pa_s=BULK_VISCOSITY_PA_S),
        working_temperature_c=(4.0, 37.0),
        crosslinking="none",
    )
    cells = CellPayload(
        name="test_cells",
        cell_type="test",
        cell_density_per_mL=1.0e6,
        max_wall_shear_stress_pa=exact_stress,
    )
    syringe = DisplacementSyringe(
        syringe_id=0,
        barrel_inner_diameter_mm=4.65,
        total_volume_uL=1000.0,
        needle=Needle(inner_diameter_mm=NEEDLE_ID_MM, length_mm=12.7),
        bioink=bioink,
        cell_payload=cells,
        temperature_setpoint_c=20.0,
    )
    report = validate_path([move], {0: syringe})
    assert report.max_observed_pa() == exact_stress
    assert report.violations == ()


def test_boundary_just_below_threshold_does_not_raise() -> None:
    syringe = _build_syringe()
    q = _q_uL_per_s_for_target_stress(THRESHOLD_PA * (1.0 - 1e-6))
    move = _build_move(_volume_uL_for_flow(q))
    report = validate_path([move], {0: syringe})
    assert report.max_observed_pa() < THRESHOLD_PA
    assert report.violations == ()


def test_boundary_just_above_threshold_raises() -> None:
    syringe = _build_syringe()
    q = _q_uL_per_s_for_target_stress(THRESHOLD_PA * (1.0 + 1e-6))
    move = _build_move(_volume_uL_for_flow(q))
    with pytest.raises(CellViabilityError) as exc_info:
        validate_path([move], {0: syringe})
    err = exc_info.value
    assert err.threshold_pa == THRESHOLD_PA
    assert err.computed_wall_shear_pa > THRESHOLD_PA
    # The over-threshold delta should be ~ THRESHOLD * 1e-6 ≈ 5e-3 Pa, not zero.
    assert err.computed_wall_shear_pa - THRESHOLD_PA == pytest.approx(THRESHOLD_PA * 1e-6, rel=1e-3)


def test_force_override_collects_violations() -> None:
    """With force=True, violations are recorded but not raised."""
    syringe = _build_syringe()
    q = _q_uL_per_s_for_target_stress(THRESHOLD_PA * 1.5)  # well over
    moves = [_build_move(_volume_uL_for_flow(q)) for _ in range(3)]
    # Give them distinct ids so the violations list can name each.
    moves = [
        Move(
            start=m.start,
            end=m.end,
            syringe_id=m.syringe_id,
            is_travel=m.is_travel,
            extrusion_volume_uL=m.extrusion_volume_uL,
            feed_mm_per_min=m.feed_mm_per_min,
            segment_id=f"forced_{i}",
        )
        for i, m in enumerate(moves)
    ]
    report = validate_path(moves, {0: syringe}, force=True)
    assert len(report.violations) == 3
    assert {v.segment_id for v in report.violations} == {"forced_0", "forced_1", "forced_2"}
    for v in report.violations:
        assert v.wall_shear_stress_pa > v.threshold_pa
