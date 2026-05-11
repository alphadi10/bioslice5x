"""Tests for path generation and the Newtonian shear-stress kernel."""

from __future__ import annotations

import math

import pytest

from bioslice5x.extruder.shear import newtonian_wall_shear_stress_pa
from bioslice5x.geometry.types import LayerGeometry, Polygon2D
from bioslice5x.kinematics.chain import ThreeAxisKinematics
from bioslice5x.pathing.perimeter import generate_perimeter_paths
from bioslice5x.recipe.models import SlicingParams


def _square_layer(z: float, side_mm: float) -> LayerGeometry:
    half = side_mm / 2.0
    points = (
        (-half, -half),
        (half, -half),
        (half, half),
        (-half, half),
    )
    return LayerGeometry(z=z, polygons=(Polygon2D(z=z, points=points, is_hole=False),))


def test_perimeter_paths_close_each_polygon() -> None:
    layers = [_square_layer(z=0.2, side_mm=10.0)]
    moves = generate_perimeter_paths(
        layers=layers,
        syringe_id=0,
        slicing=SlicingParams(layer_height_mm=0.2, line_width_mm=0.4),
        kinematic_chain=ThreeAxisKinematics(),
    )
    # 1 travel-to-start + 4 perimeter edges = 5 moves
    assert len(moves) == 5
    travels = [m for m in moves if m.is_travel]
    extrusions = [m for m in moves if not m.is_travel]
    assert len(travels) == 1
    assert len(extrusions) == 4
    # The perimeter should return to its starting vertex.
    assert extrusions[-1].end == extrusions[0].start


def test_extrusion_volume_matches_line_cross_section() -> None:
    """Slicer volume conservation: integrated extrusion equals geometric volume.

    Tolerance rationale (slicer vs firmware):

    The slicer computes E from `line_width × layer_height × length`, the
    same triple used for the assertion below — so the slicer-side tolerance
    is bounded by IEEE-754 rounding (`rel=1e-9` here, well above machine
    epsilon). This is **geometry-independent** and applies to any syringe.

    The operationally meaningful number is firmware plunger quantization,
    which IS syringe-size-dependent and ships with these caveats:

    - **1 mL BD slip-tip reference** (the package default
      `Syringe.barrel_inner_diameter_mm = 4.65`): barrel cross-section
      ≈ 16.97 mm². With a typical M92 ≈ 280 steps/mm, 1 µL → 16.5 plunger
      steps, so each step is ≈ 0.061 µL.
    - **3 mL syringes** (barrel ID ≈ 8.66 mm, area ≈ 58.9 mm²): at the same
      280 steps/mm, 1 µL → 4.75 steps → ≈ 0.21 µL per step. Worse per-µL
      quantization because the barrel is wider.
    - **5 mL syringes** (barrel ID ≈ 12.06 mm, area ≈ 114.2 mm²): 1 µL → 2.45
      steps → ≈ 0.41 µL per step.

    At a typical 1×10⁶ cells/mL payload, even the 5 mL syringe's 0.41 µL
    quantization is ≈ 410 cells per step — still negligible against any
    meaningful concentration error. The slicer's IEEE-754 tolerance is
    7+ orders of magnitude tighter than the worst firmware quantization
    in this range.

    **When 2d ships multi-syringe with mixed sizes**, revisit this docstring
    and ensure the quantization budget is reported per-syringe in the
    G-code header (it's already there via the meta block).
    """
    side = 10.0
    layers = [_square_layer(z=0.2, side_mm=side)]
    slicing = SlicingParams(layer_height_mm=0.2, line_width_mm=0.4)
    moves = generate_perimeter_paths(
        layers=layers, syringe_id=0, slicing=slicing, kinematic_chain=ThreeAxisKinematics()
    )
    extrusions = [m for m in moves if not m.is_travel]
    perimeter_length = 4 * side
    total_volume = sum(m.extrusion_volume_uL for m in extrusions)
    expected = perimeter_length * slicing.line_width_mm * slicing.layer_height_mm
    assert total_volume == pytest.approx(expected, rel=1e-9)


def test_newtonian_shear_known_answer() -> None:
    # Q = 1 µL/s, ID = 0.26 mm (25G), μ = 1 Pa·s
    #   r = 0.13 mm = 1.3e-4 m
    #   Q = 1e-9 m³/s
    #   τ = 4 · 1 · 1e-9 / (π · (1.3e-4)³)
    expected = (4.0 * 1.0 * 1.0e-9) / (math.pi * (1.3e-4) ** 3)
    actual = newtonian_wall_shear_stress_pa(
        flow_rate_uL_per_s=1.0,
        needle_inner_diameter_mm=0.26,
        bulk_viscosity_pa_s=1.0,
    )
    assert actual == pytest.approx(expected, rel=1e-9)


def test_newtonian_shear_zero_flow() -> None:
    assert (
        newtonian_wall_shear_stress_pa(
            flow_rate_uL_per_s=0.0,
            needle_inner_diameter_mm=0.26,
            bulk_viscosity_pa_s=1.0,
        )
        == 0.0
    )


def test_newtonian_shear_rejects_bad_inputs() -> None:
    with pytest.raises(ValueError):
        newtonian_wall_shear_stress_pa(
            flow_rate_uL_per_s=1.0,
            needle_inner_diameter_mm=0.0,
            bulk_viscosity_pa_s=1.0,
        )
    with pytest.raises(ValueError):
        newtonian_wall_shear_stress_pa(
            flow_rate_uL_per_s=1.0,
            needle_inner_diameter_mm=0.26,
            bulk_viscosity_pa_s=0.0,
        )
