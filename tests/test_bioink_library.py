"""Tests for the shipped bioink and cell libraries."""

from __future__ import annotations

import pytest

from bioslice5x.bioink.loader import (
    load_bioink_by_name,
    load_cell_by_name,
    load_default_library,
)
from bioslice5x.bioink.models import Bioink, CellPayload, RheologicalModel
from bioslice5x.errors import ProfileValidationError

SHIPPED_BIOINKS = (
    "collagen_i_8mg_per_mL",
    "gelma_10pct",
    "fibrin_25mg_per_mL",
    "alginate_3pct",
    "pegda_20pct",
)

SHIPPED_CELLS = ("general_mammalian", "hUVEC_endothelial")


def test_default_library_has_all_shipped_bioinks() -> None:
    bioinks, cells = load_default_library()
    for name in SHIPPED_BIOINKS:
        assert name in bioinks, f"missing bioink {name!r}"
    for name in SHIPPED_CELLS:
        assert name in cells, f"missing cell {name!r}"


def test_every_bioink_has_calibrated_against_field() -> None:
    bioinks, _ = load_default_library()
    for name, bioink in bioinks.items():
        assert bioink.calibrated_against, f"{name} missing calibrated_against"
        assert "uncalibrated" in bioink.calibrated_against.lower(), (
            f"{name} should declare placeholder status until lab-calibrated"
        )


def test_every_cell_has_calibrated_against_field() -> None:
    _, cells = load_default_library()
    for name, cell in cells.items():
        assert cell.calibrated_against, f"{name} missing calibrated_against"


def test_load_bioink_by_name_round_trip() -> None:
    bioink = load_bioink_by_name("collagen_i_8mg_per_mL")
    assert isinstance(bioink, Bioink)
    assert bioink.rheology.kind == "power_law"
    assert bioink.rheology.consistency_k is not None
    assert bioink.rheology.consistency_k > 0


def test_load_cell_by_name_round_trip() -> None:
    cell = load_cell_by_name("hUVEC_endothelial")
    assert isinstance(cell, CellPayload)
    # The HUVEC default must be stricter than the general baseline.
    general = load_cell_by_name("general_mammalian")
    assert cell.max_wall_shear_stress_pa < general.max_wall_shear_stress_pa


def test_unknown_bioink_raises_helpful_error() -> None:
    with pytest.raises(ProfileValidationError) as exc:
        load_bioink_by_name("nonexistent_bioink")
    assert "available" in str(exc.value).lower()


def test_rheology_model_requires_correct_fields_for_kind() -> None:
    with pytest.raises(ValueError, match="newtonian rheology requires"):
        RheologicalModel(kind="newtonian")
    with pytest.raises(ValueError, match="power_law requires"):
        RheologicalModel(kind="power_law", consistency_k=10.0)
    with pytest.raises(ValueError, match="herschel_bulkley requires"):
        RheologicalModel(kind="herschel_bulkley", consistency_k=10.0, flow_index_n=0.5)


def test_bioink_rejects_inverted_temperature_window() -> None:
    with pytest.raises(ValueError, match="working_temperature_c"):
        Bioink(
            name="bad",
            density_g_per_mL=1.0,
            rheology=RheologicalModel(kind="newtonian", viscosity_pa_s=1.0),
            working_temperature_c=(30.0, 20.0),
            crosslinking="none",
        )
