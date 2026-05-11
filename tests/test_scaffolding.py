"""Smoke-test that the package imports cleanly and the public surface is intact."""

from __future__ import annotations

import importlib

import pytest

import bioslice5x
from bioslice5x.errors import (
    BathCollisionError,
    BioSlice5XError,
    CellViabilityError,
    KinematicSingularityError,
    ProfileValidationError,
)

SUBMODULES = (
    "bioslice5x.geometry",
    "bioslice5x.kinematics",
    "bioslice5x.kinematics.canonical",
    "bioslice5x.kinematics.chain",
    "bioslice5x.kinematics.singularity",
    "bioslice5x.pathing",
    "bioslice5x.extruder",
    "bioslice5x.bioink",
    "bioslice5x.bioink.models",
    "bioslice5x.bioink.loader",
    "bioslice5x.postprocessor",
    "bioslice5x.visualization",
    "bioslice5x.profile",
    "bioslice5x.profile.models",
    "bioslice5x.profile.loader",
    "bioslice5x.recipe",
    "bioslice5x.recipe.models",
    "bioslice5x.recipe.loader",
    "bioslice5x.slicer",
    "bioslice5x.cli",
)


def test_version_string() -> None:
    assert isinstance(bioslice5x.__version__, str)
    assert bioslice5x.__version__.count(".") >= 2


@pytest.mark.parametrize("name", SUBMODULES)
def test_submodules_importable(name: str) -> None:
    module = importlib.import_module(name)
    assert module is not None


def test_top_level_public_surface_present() -> None:
    for attr in ("Slicer", "SliceResult", "load_mesh", "load_profile", "load_recipe"):
        assert hasattr(bioslice5x, attr), f"missing public symbol {attr!r}"


def test_cell_viability_error_is_base_subclass() -> None:
    err = CellViabilityError(
        segment_id="seg-0",
        computed_wall_shear_pa=2500.0,
        threshold_pa=2000.0,
        bioink_name="collagen_i_8mg_per_mL",
        cell_type="hiPSC-CM",
        remediation="lower feedrate or use larger gauge",
    )
    assert isinstance(err, BioSlice5XError)
    rendered = str(err)
    assert "seg-0" in rendered
    assert "2500" in rendered
    assert "hiPSC-CM" in rendered


def test_all_errors_inherit_base() -> None:
    for cls in (
        CellViabilityError,
        KinematicSingularityError,
        BathCollisionError,
        ProfileValidationError,
    ):
        assert issubclass(cls, BioSlice5XError)


def test_cli_help_runs() -> None:
    from bioslice5x import cli

    parser = cli.build_parser()
    assert parser.prog == "bioslice5x"
