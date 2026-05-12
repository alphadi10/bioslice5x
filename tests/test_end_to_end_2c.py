"""Phase 2c end-to-end test: conformal wrap-around-axis cylinder.

Validates the conformal pipeline shape: mesh → wrap-around slice → kinematic
transform (C sweeping through θ) → G-code with per-segment swivel tokens.

Per reviewer guardrail, 2c v1 ships **wrap-around-axis only** (no
arbitrary curved layers). The test uses a roughly-cylindrical mesh and the
shipped `open5x_prusa` profile to exercise the full pipeline end-to-end.
"""

from __future__ import annotations

import sys
from typing import Any, cast

import pytest
import trimesh

from bioslice5x import Slicer, load_profile
from bioslice5x.bath.models import PlaneBath
from bioslice5x.recipe.models import (
    FixedOrientation,
    Needle,
    Recipe,
    SlicingParams,
    Syringe,
    WrapAroundAxisSlicing,
)

pytestmark = pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="emit_rrf uses `from datetime import UTC` (Python 3.11+)",
)


def _cylinder_mesh(radius_mm: float = 5.0, height_mm: float = 10.0) -> trimesh.Trimesh:
    cyl: Any = trimesh.creation.cylinder(radius=radius_mm, height=height_mm, sections=24)
    cyl.apply_translation([0.0, 0.0, height_mm / 2.0])
    return cast(trimesh.Trimesh, cyl)


def _conformal_recipe(*, with_bath: bool) -> Recipe:
    return Recipe(
        name="conformal_cylinder",
        syringes=[
            Syringe(
                id=0,
                bioink="collagen_i_8mg_per_mL",
                cell_payload="general_mammalian",
                needle=Needle(inner_diameter_mm=0.84, length_mm=12.7, gauge_label="18G"),
            )
        ],
        slicing=SlicingParams(
            layer_height_mm=0.4,
            line_width_mm=0.5,
            print_speed_mm_per_min=60.0,
            mode=WrapAroundAxisSlicing(
                kind="wrap_around_axis",
                wrap_axis="z",
                cylinder_radius_mm=5.0,
                arc_start_deg=-180.0,
                arc_end_deg=180.0,
            ),
        ),
        print_orientation=FixedOrientation(),  # ignored in conformal mode
        bath=PlaneBath(surface_z_mm=0.0, travel_speed_multiplier_in_bath=0.3)
        if with_bath
        else None,
    )


def test_conformal_cylinder_produces_gcode_with_C_tokens() -> None:
    """The conformal pipeline produces G-code where every G1 line carries a
    C token, because every move's destination has a non-trivial swivel.
    """
    profile = load_profile("open5x_prusa")
    result = Slicer(profile=profile, recipe=_conformal_recipe(with_bath=False)).slice(
        _cylinder_mesh(radius_mm=5.0, height_mm=10.0)
    )
    gcode = result.gcode
    g1_lines = [line for line in gcode.splitlines() if line.startswith("G1 ")]
    assert len(g1_lines) > 0
    # Every G1 carries an A (always 0 in this mode) and a C token.
    for line in g1_lines:
        tokens = line.split()
        a_tokens = [t for t in tokens if t.startswith("A")]
        c_tokens = [t for t in tokens if t.startswith("C")]
        assert len(a_tokens) == 1, f"missing A token: {line!r}"
        assert len(c_tokens) == 1, f"missing C token: {line!r}"
    # The C values sweep across the layer — at least 8 distinct values present.
    # Find the C token by prefix to stay robust against trailing comment
    # tokens like `;STRESS:<Pa>` that the postprocessor emits.
    distinct_c: set[str] = set()
    for line in g1_lines:
        for tok in line.split():
            if tok.startswith("C") and len(tok) > 1 and tok[1] in "-0123456789.":
                distinct_c.add(tok)
                break
    assert len(distinct_c) >= 8, f"C should vary across the wrap; got {distinct_c}"


def test_conformal_with_bath_applies_speed_reduction() -> None:
    """Travel moves below the bath surface (z < 0) get the bath's reduced
    feedrate; travels above use the full travel speed.
    """
    profile = load_profile("open5x_prusa")
    recipe = _conformal_recipe(with_bath=True)
    bath = recipe.bath
    assert bath is not None
    result = Slicer(profile=profile, recipe=recipe).slice(_cylinder_mesh())
    travels = [m for m in result.moves if m.is_travel]
    if not travels:
        return  # no travels in this trivial single-perimeter print
    base_speed = recipe.slicing.travel_speed_mm_per_min
    for move in travels:
        if move.end.z < bath.surface_z_mm:
            expected = base_speed * bath.travel_speed_multiplier_in_bath
        else:
            expected = base_speed
        assert abs(move.feed_mm_per_min - expected) < 1e-9


def test_conformal_meta_block_in_header() -> None:
    """Header should declare kinematic_chain=tilt_swivel for the Prusa profile."""
    profile = load_profile("open5x_prusa")
    result = Slicer(profile=profile, recipe=_conformal_recipe(with_bath=False)).slice(
        _cylinder_mesh()
    )
    assert ";META: kinematic_chain=tilt_swivel" in result.gcode
    assert ";META: extrusion_mode=displacement" in result.gcode
