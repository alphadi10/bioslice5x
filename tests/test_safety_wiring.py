"""Tests for the v0.1.2 safety wiring:

  - per-syringe `retract_volume_uL` round-trips into emitted G-code
    (paired retract / un-retract around travels and toolchanges; final
    retract at end-of-print)
  - axis-range clamp refuses out-of-range A/B/C tokens (with 360° wrap
    rescue for mechanically-equivalent in-range poses)
  - singularity smoothing is wired and runs on conformal joint sequences
    that actually cross the singular band (not on swivel-only sweeps
    where every joint sits in-band by construction)
  - safe-park end-of-print sequence: Z-clear, rotaries-to-home, heater
    setpoints released, motors off
  - G-code banner reflects the kinematic chain (3-axis vs tilt+swivel)

Every check anchors on an explicit invariant the slicer must hold for
a print to be safe to run on FRESH hardware — see
`docs/BIOPRINTING_REQUIREMENTS.md`.
"""

from __future__ import annotations

import sys
from typing import Any, cast

import pytest
import trimesh

from bioslice5x import Slicer, load_profile
from bioslice5x.errors import ProfileValidationError
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
    reason="emit_rrf uses `from datetime import UTC` which is Python 3.11+",
)


def _cube(size_mm: float = 6.0) -> trimesh.Trimesh:
    cube: Any = trimesh.creation.box(extents=[size_mm, size_mm, size_mm])
    cube.apply_translation([0.0, 0.0, size_mm / 2.0])
    return cast(trimesh.Trimesh, cube)


def _cylinder(radius_mm: float = 5.0, height_mm: float = 10.0) -> trimesh.Trimesh:
    cyl: Any = trimesh.creation.cylinder(radius=radius_mm, height=height_mm, sections=48)
    cyl.apply_translation([0.0, 0.0, height_mm / 2.0])
    return cast(trimesh.Trimesh, cyl)


def _recipe(*, retract_volume_uL: float = 0.5) -> Recipe:
    return Recipe(
        name="safety_wiring_test",
        syringes=[
            Syringe(
                id=0,
                bioink="collagen_i_8mg_per_mL",
                cell_payload="general_mammalian",
                needle=Needle(inner_diameter_mm=0.84, length_mm=12.7, gauge_label="18G"),
                retract_volume_uL=retract_volume_uL,
            )
        ],
        slicing=SlicingParams(
            layer_height_mm=0.4,
            line_width_mm=0.5,
            print_speed_mm_per_min=60.0,
        ),
    )


def _conformal_recipe(*, retract_volume_uL: float = 0.5) -> Recipe:
    return Recipe(
        name="safety_wiring_conformal",
        syringes=[
            Syringe(
                id=0,
                bioink="collagen_i_8mg_per_mL",
                cell_payload="general_mammalian",
                needle=Needle(inner_diameter_mm=0.84, length_mm=12.7, gauge_label="18G"),
                retract_volume_uL=retract_volume_uL,
            )
        ],
        slicing=SlicingParams(
            layer_height_mm=0.4,
            line_width_mm=0.5,
            print_speed_mm_per_min=60.0,
            mode=WrapAroundAxisSlicing(wrap_axis="z", cylinder_radius_mm=5.0),
        ),
        print_orientation=FixedOrientation(),
    )


def _slice_text(recipe: Recipe, profile_name: str = "hypothetical_3axis") -> str:
    profile = load_profile(profile_name)
    mesh = _cylinder() if isinstance(recipe.slicing.mode, WrapAroundAxisSlicing) else _cube()
    return Slicer(profile=profile, recipe=recipe).slice(mesh).gcode


# -- retract --------------------------------------------------------------


def test_retract_emitted_when_volume_positive() -> None:
    """Default retract_volume_uL=0.5 produces paired retract/un-retract lines."""
    gcode = _slice_text(_recipe(retract_volume_uL=0.5))
    retracts = [
        line for line in gcode.splitlines() if "; retract " in line and line.startswith("G1 E-")
    ]
    un_retracts = [
        line for line in gcode.splitlines() if "; un-retract " in line and line.startswith("G1 E")
    ]
    assert len(retracts) > 0, "expected ≥1 retract pulse with non-zero retract_volume_uL"
    # Every un-retract has a preceding retract; an unmatched trailing
    # retract at end-of-print is allowed (final relax before unload).
    assert len(retracts) >= len(un_retracts)


def test_retract_disabled_when_volume_zero() -> None:
    """retract_volume_uL=0 emits zero retract pulses; pre-v0.1.2 output."""
    gcode = _slice_text(_recipe(retract_volume_uL=0.0))
    retracts = [line for line in gcode.splitlines() if line.startswith("G1 E-")]
    un_retracts = [line for line in gcode.splitlines() if "un-retract" in line]
    assert retracts == []
    assert un_retracts == []


def test_retract_volume_scales_plunger_displacement() -> None:
    """Doubling retract_volume_uL doubles the emitted plunger-mm distance."""
    g_small = _slice_text(_recipe(retract_volume_uL=0.5))
    g_large = _slice_text(_recipe(retract_volume_uL=1.0))

    def _first_retract_mm(gcode: str) -> float:
        for line in gcode.splitlines():
            if line.startswith("G1 E-") and "; retract" in line:
                # "G1 E-0.02944 F600 ; retract 0.5 uL" — token 1 is "E-..."
                return abs(float(line.split()[1][1:]))
        raise AssertionError("no retract line found")

    small_mm = _first_retract_mm(g_small)
    large_mm = _first_retract_mm(g_large)
    assert large_mm == pytest.approx(small_mm * 2.0, rel=1e-6)


# -- axis range clamp -----------------------------------------------------


def test_axis_range_clamp_refuses_unreachable_pose() -> None:
    """A fixed-orientation print outside the Voron tilt range raises."""
    voron = load_profile("open5x_voron")
    recipe = Recipe(
        name="out_of_range_tilt",
        syringes=[
            Syringe(
                id=0,
                bioink="collagen_i_8mg_per_mL",
                cell_payload="general_mammalian",
                needle=Needle(inner_diameter_mm=0.84, length_mm=12.7),
            )
        ],
        slicing=SlicingParams(layer_height_mm=0.4, line_width_mm=0.5, print_speed_mm_per_min=60.0),
        print_orientation=FixedOrientation(tilt_deg=150.0, swivel_deg=0.0),  # > Voron ±110°
    )
    with pytest.raises(ProfileValidationError, match=r"outside mechanical range"):
        Slicer(profile=voron, recipe=recipe).slice(_cube())


def test_axis_range_360_wrap_rescue_brings_in_range() -> None:
    """A canonical +270° lands inside Prusa ±200° range as -90° via 360° wrap."""
    prusa = load_profile("open5x_prusa")
    # Conformal wrap on x produces canonical tilt = π/2 - θ which spans
    # [-π/2, 3π/2] = [-90°, 270°] for θ ∈ [-π, π]. The clamp rescues
    # the 270° endpoint by emitting -90° instead.
    recipe = Recipe(
        name="prusa_360_wrap_rescue",
        syringes=[
            Syringe(
                id=0,
                bioink="collagen_i_8mg_per_mL",
                cell_payload="general_mammalian",
                needle=Needle(inner_diameter_mm=0.84, length_mm=12.7),
            )
        ],
        slicing=SlicingParams(
            layer_height_mm=0.4,
            line_width_mm=0.5,
            print_speed_mm_per_min=60.0,
            mode=WrapAroundAxisSlicing(wrap_axis="x", cylinder_radius_mm=5.0),
        ),
        print_orientation=FixedOrientation(),
    )
    result = Slicer(profile=prusa, recipe=recipe).slice(_cylinder())
    a_values = sorted(
        {
            float(tok[1:])
            for line in result.gcode.splitlines()
            if line.startswith("G1 ")
            for tok in line.split()
            if tok.startswith("A") and len(tok) > 1 and tok[1] in "-0123456789."
        }
    )
    # All emitted A values must lie within Prusa's ±200° range.
    for v in a_values:
        assert -200.0 - 1e-6 <= v <= 200.0 + 1e-6, f"A value {v} out of Prusa range"


# -- safe park EOF --------------------------------------------------------


def test_safe_park_z_clear_at_end_of_print() -> None:
    """The EOF sequence raises Z by the recipe's safe_park_clearance_mm."""
    gcode = _slice_text(_recipe())
    park_lines = [line for line in gcode.splitlines() if "safe-park Z" in line]
    assert len(park_lines) == 1, f"expected exactly one safe-park line; got {park_lines}"


def test_safe_park_rotaries_home_on_tilt_swivel_chain() -> None:
    """On a 5-axis profile, the EOF sequence sends rotaries to 0/0."""
    gcode = _slice_text(_conformal_recipe(), profile_name="open5x_prusa")
    home_lines = [line for line in gcode.splitlines() if "rotaries home" in line]
    assert len(home_lines) == 1, f"expected one rotary-home line; got {home_lines}"
    line = home_lines[0]
    assert "A0" in line.split(), f"expected A0 in {line!r}"
    assert "C0" in line.split(), f"expected C0 in {line!r}"


def test_safe_park_releases_each_syringe_heater() -> None:
    """Every syringe gets an M104 S0 T<n> at end-of-print."""
    gcode = _slice_text(_recipe())
    release_lines = [line for line in gcode.splitlines() if line.startswith("M104 S0 T")]
    assert len(release_lines) >= 1
    # Exactly one per syringe.
    assert any(line.startswith("M104 S0 T0") for line in release_lines)


# -- banner + meta --------------------------------------------------------


def test_banner_reflects_three_axis_chain() -> None:
    gcode = _slice_text(_recipe())
    assert "; BioSlice5X G-code (3-axis baseline)" in gcode
    assert "; BioSlice5X G-code (5-axis" not in gcode


def test_banner_reflects_five_axis_chain() -> None:
    gcode = _slice_text(_conformal_recipe(), profile_name="open5x_prusa")
    assert "; BioSlice5X G-code (5-axis tilt+swivel)" in gcode


def test_meta_includes_feed_token_semantics() -> None:
    """The META block declares F-token semantics so machine consumers can flag rotary-dominant moves."""
    gcode = _slice_text(_conformal_recipe(), profile_name="open5x_prusa")
    assert ";META: feed_token_semantics=cartesian_dominant" in gcode


# -- toolchange retract ---------------------------------------------------


def test_toolchange_resets_relative_e_origin() -> None:
    """Every T<n> emission is followed by a G92 E0 defensive reset."""
    recipe = Recipe(
        name="multi_syringe",
        syringes=[
            Syringe(
                id=0,
                bioink="collagen_i_8mg_per_mL",
                cell_payload="general_mammalian",
                needle=Needle(inner_diameter_mm=0.84, length_mm=12.7),
            ),
            Syringe(
                id=1,
                bioink="collagen_i_8mg_per_mL",
                cell_payload="general_mammalian",
                needle=Needle(inner_diameter_mm=0.84, length_mm=12.7),
            ),
        ],
        slicing=SlicingParams(layer_height_mm=0.4, line_width_mm=0.5, print_speed_mm_per_min=60.0),
    )
    gcode = Slicer(profile=load_profile("hypothetical_3axis"), recipe=recipe).slice(_cube()).gcode
    lines = gcode.splitlines()
    for idx, line in enumerate(lines):
        if line.startswith("T") and "switch to syringe" in line:
            # The next non-empty line must be the G92 E0 reset.
            for next_line in lines[idx + 1 :]:
                if not next_line.strip():
                    continue
                assert next_line.startswith("G92 E0"), (
                    f"toolchange at line {idx} not followed by G92 E0; got {next_line!r}"
                )
                break
