"""Phase 2a end-to-end test: cube STL → flat-sliced → valid 3-axis G-code.

The test programmatically constructs a tiny cube (no fixture file), runs the
full library pipeline, and asserts a few properties of the output. This is
the regression that locks down the pipeline shape for everything that follows.
"""

from __future__ import annotations

import sys
from typing import Any, cast

import pytest
import trimesh

from bioslice5x import CellViabilityError, Slicer, load_profile
from bioslice5x.recipe.models import Needle, Recipe, SlicingParams, Syringe

pytestmark = pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="emit_rrf uses `from datetime import UTC` (Python 3.11+)",
)


def _cube_mesh(size_mm: float = 6.0) -> trimesh.Trimesh:
    cube: Any = trimesh.creation.box(extents=[size_mm, size_mm, size_mm])
    cube.apply_translation([0.0, 0.0, size_mm / 2.0])
    return cast(trimesh.Trimesh, cube)


def _safe_recipe(*, print_speed_mm_per_min: float = 60.0) -> Recipe:
    return Recipe(
        name="phase_2a_cube",
        syringes=[
            Syringe(
                id=0,
                bioink="collagen_i_8mg_per_mL",
                cell_payload="general_mammalian",
                needle=Needle(inner_diameter_mm=0.84, length_mm=12.7, gauge_label="18G"),
                barrel_inner_diameter_mm=4.65,
                total_volume_uL=1000.0,
            )
        ],
        slicing=SlicingParams(
            layer_height_mm=0.4,
            line_width_mm=0.5,
            print_speed_mm_per_min=print_speed_mm_per_min,
        ),
    )


def test_end_to_end_cube_produces_valid_gcode() -> None:
    profile = load_profile("hypothetical_3axis")
    slicer = Slicer(profile=profile, recipe=_safe_recipe())
    result = slicer.slice(_cube_mesh(size_mm=6.0))
    text = result.gcode

    # Basic structural checks on the G-code.
    assert text.startswith("; ====")
    assert "G90" in text
    assert "M83" in text
    assert "; ---- start of print ----" in text
    assert "; ---- end of print ----" in text
    assert "M84" in text

    # The print contains travel and extrusion moves.
    travel_moves = sum(1 for m in result.moves if m.is_travel)
    extrusion_moves = sum(1 for m in result.moves if not m.is_travel)
    assert travel_moves >= 1
    assert extrusion_moves > 0

    # Total bioink volume is plausible for a 6mm cube perimeter print.
    total_uL = result.total_bioink_uL_by_syringe[0]
    assert 1.0 < total_uL < 200.0, f"unexpected total volume {total_uL} uL"

    # Stress report should be populated and well below the threshold for an 18G
    # needle at a slow speed.
    assert result.stress_report.max_observed_pa() > 0
    assert result.stress_report.max_observed_pa() < 5000.0


def test_cell_viability_error_blocks_unsafe_print() -> None:
    """A pathologically fast print through a fine needle must be refused."""
    profile = load_profile("hypothetical_3axis")
    recipe = Recipe(
        name="should_fail",
        syringes=[
            Syringe(
                id=0,
                bioink="collagen_i_8mg_per_mL",
                cell_payload="hUVEC_endothelial",  # stricter, 2 kPa limit
                needle=Needle(inner_diameter_mm=0.16, length_mm=12.7, gauge_label="30G"),
            )
        ],
        slicing=SlicingParams(
            layer_height_mm=0.2,
            line_width_mm=0.4,
            print_speed_mm_per_min=6000.0,  # very fast through a 30G needle
        ),
    )
    slicer = Slicer(profile=profile, recipe=recipe)
    with pytest.raises(CellViabilityError) as exc:
        slicer.slice(_cube_mesh(size_mm=6.0))
    msg = str(exc.value)
    assert "collagen_i_8mg_per_mL" in msg
    assert "HUVEC" in msg or "endothelial" in msg


def test_force_override_emits_tagged_gcode() -> None:
    """The same unsafe recipe with force=True emits G-code with the override tag."""
    profile = load_profile("hypothetical_3axis")
    recipe = Recipe(
        name="forced_unsafe",
        syringes=[
            Syringe(
                id=0,
                bioink="collagen_i_8mg_per_mL",
                cell_payload="hUVEC_endothelial",
                needle=Needle(inner_diameter_mm=0.16, length_mm=12.7),
            )
        ],
        slicing=SlicingParams(print_speed_mm_per_min=6000.0),
    )
    slicer = Slicer(profile=profile, recipe=recipe)
    result = slicer.slice(_cube_mesh(size_mm=6.0), force=True)
    # Phase 2b upgraded the override marker from a single comment to a
    # multi-line "WARNING: SAFETY_OVERRIDE" banner with per-violation
    # detail; the banner string is what we pin now.
    assert "WARNING: SAFETY_OVERRIDE" in result.gcode
    # The META block also flips safety_override=true.
    assert ";META: safety_override=true" in result.gcode
    # At least one violation segment is named in the banner.
    assert len(result.stress_report.violations) > 0


def test_dry_run_truncates_moves() -> None:
    profile = load_profile("hypothetical_3axis")
    slicer = Slicer(profile=profile, recipe=_safe_recipe())
    result = slicer.slice(_cube_mesh(size_mm=6.0))
    dry = result.dry_run(n_moves=3)
    # `dry_run` counts toolpath-motion G1 lines (those carrying X/Y/Z/A/B/C
    # tokens). Plunger-only retract / un-retract pulses are accessories to
    # their wrapping travel and pass through without burning the budget,
    # and the safe-park EOF Z move is always preserved.
    motion_letters = ("X", "Y", "Z", "A", "B", "C")
    motion_g1 = [
        line
        for line in dry.splitlines()
        if line.startswith("G1 ")
        and any(t and t[0] in motion_letters for t in line.split()[1:])
        and "safe-park" not in line
    ]
    assert len(motion_g1) == 3
    assert "dry-run truncated" in dry


# Removed: `test_phase_2b_rejects_multi_syringe` was a Phase 2b-era contract
# asserting the slicer raises NotImplementedError for N>1 syringes. Phase 2d
# shipped multi-syringe support (Region(kind="all") only — bbox/submesh
# still deferred to v0.1.1), so the slicer accepts N>=1. Multi-syringe
# behaviour is now covered by `tests/test_multi_syringe.py`.
