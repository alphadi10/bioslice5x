"""Tests for profile and recipe loaders / models."""

from __future__ import annotations

from pathlib import Path

import pytest

from bioslice5x.errors import ProfileValidationError
from bioslice5x.profile.loader import load_profile
from bioslice5x.profile.models import (
    BuildVolume,
    KinematicChain,
    MachineProfile,
    TiltSwivelAxis,
)
from bioslice5x.recipe.loader import load_recipe
from bioslice5x.recipe.models import Needle, Recipe, Region, SlicingParams, Syringe


def test_load_hypothetical_3axis_profile() -> None:
    profile = load_profile("hypothetical_3axis")
    assert profile.name == "hypothetical_3axis"
    assert profile.kinematic_chain.kind == "three_axis"
    assert profile.kinematic_chain.tilt is None
    assert profile.kinematic_chain.swivel is None


def test_unknown_profile_raises() -> None:
    with pytest.raises(ProfileValidationError):
        load_profile("no_such_profile")


def test_tilt_swivel_chain_requires_both_axes() -> None:
    with pytest.raises(ValueError, match="requires both"):
        KinematicChain(kind="tilt_swivel")


def test_three_axis_chain_rejects_rotaries() -> None:
    with pytest.raises(ValueError, match="must not declare"):
        KinematicChain(
            kind="three_axis",
            tilt=TiltSwivelAxis(rotates_about="x", letter="A", range_deg=(-90.0, 90.0)),
        )


def test_machine_profile_accepts_tilt_swivel_chain() -> None:
    profile = MachineProfile(
        name="t",
        build_volume=BuildVolume(x_mm=(0.0, 50.0), y_mm=(0.0, 50.0), z_mm=(0.0, 50.0)),
        kinematic_chain=KinematicChain(
            kind="tilt_swivel",
            tilt=TiltSwivelAxis(rotates_about="x", letter="A", range_deg=(-90.0, 90.0)),
            swivel=TiltSwivelAxis(
                rotates_about="z", letter="C", range_deg=(-360.0, 360.0), invert=True
            ),
        ),
    )
    assert profile.kinematic_chain.tilt is not None
    assert profile.kinematic_chain.swivel is not None
    assert profile.kinematic_chain.swivel.invert is True


def test_load_recipe_round_trip(tmp_path: Path) -> None:
    recipe_yaml = """
name: cube_test
syringes:
  - id: 0
    bioink: collagen_i_8mg_per_mL
    cell_payload: general_mammalian
    needle:
      inner_diameter_mm: 0.84
      length_mm: 12.7
      gauge_label: "18G"
    region:
      kind: all
slicing:
  layer_height_mm: 0.4
  line_width_mm: 0.5
  print_speed_mm_per_min: 60.0
"""
    f = tmp_path / "recipe.yaml"
    f.write_text(recipe_yaml)
    recipe = load_recipe(f)
    assert recipe.name == "cube_test"
    assert len(recipe.syringes) == 1
    assert recipe.syringes[0].bioink == "collagen_i_8mg_per_mL"
    assert recipe.syringes[0].region.kind == "all"


def test_print_orientation_rejects_typo_kind(tmp_path: Path) -> None:
    """A typo in `print_orientation.kind` must raise a clear validation error
    naming the offending field — not fall through to a default.

    When 2c adds new kinds, the Literal expands but the failure mode for
    misspellings stays the same: pydantic raises with the expected values
    listed in the error message.
    """
    recipe_yaml = """
name: typo_test
syringes:
  - id: 0
    bioink: collagen_i_8mg_per_mL
    cell_payload: general_mammalian
    needle:
      inner_diameter_mm: 0.84
      length_mm: 12.7
print_orientation:
  kind: perlayer    # typo — should be one of: fixed
  tilt_deg: 10.0
  swivel_deg: 0.0
"""
    f = tmp_path / "recipe.yaml"
    f.write_text(recipe_yaml)
    with pytest.raises(ProfileValidationError) as exc:
        load_recipe(f)
    rendered = str(exc.value)
    # The error should at minimum reference the bad value, the field, or
    # the allowed values — anything that gives the user a fighting chance
    # at finding the typo.
    assert (
        "perlayer" in rendered
        or "fixed" in rendered
        or "kind" in rendered
        or "print_orientation" in rendered
    )


def test_recipe_rejects_duplicate_syringe_ids() -> None:
    with pytest.raises(ValueError, match="unique"):
        Recipe(
            name="bad",
            syringes=[
                Syringe(
                    id=0,
                    bioink="x",
                    cell_payload="y",
                    needle=Needle(inner_diameter_mm=0.4, length_mm=12.7),
                    region=Region(),
                ),
                Syringe(
                    id=0,  # duplicate
                    bioink="x",
                    cell_payload="y",
                    needle=Needle(inner_diameter_mm=0.4, length_mm=12.7),
                ),
            ],
            slicing=SlicingParams(),
        )
