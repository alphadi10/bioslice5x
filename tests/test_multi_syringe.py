"""Phase 2d / v0.1.0 multi-syringe end-to-end.

The recipe schema supported multiple syringes from day one (the recipe
regions pattern with kind="all" as N=1 of the general form). v0.1.0 lifts
the Slicer's N=1 restriction and emits tool-change G-code per syringe.

What v0.1.0 ships:
- N syringes, each with `Region(kind="all")` — every syringe prints the
  whole mesh. Useful for support material + structural ink, or for any
  multi-material print where regions are not yet bbox-resolved.
- Tool-change `T<n>` line per syringe-id switch.
- Aggregated stress report (per-syringe entries already supported).
- Aggregated G-code header listing every syringe.

What v0.1.1 will add (filed as known limitations):
- `Region(kind="bbox")` and `Region(kind="submesh")` — proper region
  resolution.
- Per-bioink retract/purge sequences at tool-change.
- Smart layer ordering minimizing inter-region travels.
"""

from __future__ import annotations

import sys
from typing import Any, cast

import pytest
import trimesh

pytestmark = pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="emit_rrf uses `from datetime import UTC` (Python 3.11+)",
)

from bioslice5x import Slicer, load_profile  # noqa: E402
from bioslice5x.recipe.models import (  # noqa: E402
    Needle,
    Recipe,
    SlicingParams,
    Syringe,
)


def _cube_mesh(size_mm: float = 6.0) -> trimesh.Trimesh:
    cube: Any = trimesh.creation.box(extents=[size_mm, size_mm, size_mm])
    cube.apply_translation([0.0, 0.0, size_mm / 2.0])
    return cast(trimesh.Trimesh, cube)


def _two_syringe_recipe() -> Recipe:
    return Recipe(
        name="two_syringe_cube",
        syringes=[
            Syringe(
                id=0,
                bioink="collagen_i_8mg_per_mL",
                cell_payload="general_mammalian",
                needle=Needle(inner_diameter_mm=0.84, length_mm=12.7, gauge_label="18G"),
            ),
            Syringe(
                id=1,
                bioink="alginate_3pct",
                cell_payload="general_mammalian",
                needle=Needle(inner_diameter_mm=0.84, length_mm=12.7, gauge_label="18G"),
            ),
        ],
        slicing=SlicingParams(
            layer_height_mm=0.4,
            line_width_mm=0.5,
            print_speed_mm_per_min=60.0,
        ),
    )


def test_two_syringe_print_emits_both_tool_tokens() -> None:
    profile = load_profile("hypothetical_3axis")
    slicer = Slicer(profile=profile, recipe=_two_syringe_recipe())
    result = slicer.slice(_cube_mesh())
    lines = result.gcode.splitlines()
    t0_lines = [line for line in lines if line.startswith("T0")]
    t1_lines = [line for line in lines if line.startswith("T1")]
    assert len(t0_lines) >= 1, "expected at least one T0 tool-change line"
    assert len(t1_lines) >= 1, "expected at least one T1 tool-change line"


def test_two_syringe_header_lists_both_syringes() -> None:
    profile = load_profile("hypothetical_3axis")
    slicer = Slicer(profile=profile, recipe=_two_syringe_recipe())
    result = slicer.slice(_cube_mesh())
    assert "Syringe 0:" in result.gcode
    assert "Syringe 1:" in result.gcode
    assert ";META: syringe_count=2" in result.gcode


def test_two_syringe_stress_report_per_syringe() -> None:
    profile = load_profile("hypothetical_3axis")
    slicer = Slicer(profile=profile, recipe=_two_syringe_recipe())
    result = slicer.slice(_cube_mesh())
    assert 0 in result.stress_report.max_by_syringe
    assert 1 in result.stress_report.max_by_syringe
    # Both syringes did work; both observed non-zero stress.
    assert result.stress_report.max_by_syringe[0] > 0
    assert result.stress_report.max_by_syringe[1] > 0


def test_region_all_constructs() -> None:
    """`RegionAll` is the default per-syringe region — N=1 of the general form."""
    from bioslice5x.recipe.models import RegionAll

    region = RegionAll()
    assert region.kind == "all"


def test_region_bbox_validates_min_le_max() -> None:
    """`RegionBBox` rejects min > max on any axis with a clear message."""
    from pydantic import ValidationError

    from bioslice5x.recipe.models import RegionBBox

    # Valid bbox round-trips.
    ok = RegionBBox(min=(-1.0, -1.0, 0.0), max=(1.0, 1.0, 2.0))
    assert ok.kind == "bbox"
    assert ok.min == (-1.0, -1.0, 0.0)
    # Invalid: min.x > max.x.
    with pytest.raises(ValidationError, match=r"bbox min\.x"):
        RegionBBox(min=(5.0, 0.0, 0.0), max=(1.0, 1.0, 1.0))


def test_bbox_region_clips_layers_in_slice() -> None:
    """The Slicer applies bbox clipping per syringe — confirm by slice volume.

    A two-syringe recipe printing a 10mm cube: syringe 0 with a half-sized
    bbox (≤ 5mm in x) produces strictly less extrusion than the full mesh,
    and syringe 1 with `kind=all` produces the full mesh extrusion. The
    sum of unique segment ids across syringes shows the bbox syringe owns
    a strict subset.
    """
    from typing import cast

    import trimesh

    from bioslice5x import Slicer, load_profile
    from bioslice5x.recipe.models import (
        Needle,
        Recipe,
        RegionAll,
        RegionBBox,
        SlicingParams,
        Syringe,
    )

    cube: Any = trimesh.creation.box(extents=[10.0, 10.0, 2.0])
    cube.apply_translation([0.0, 0.0, 1.0])
    mesh = cast(trimesh.Trimesh, cube)
    needle = Needle(inner_diameter_mm=0.84, length_mm=12.7)
    recipe = Recipe(
        name="bbox_test",
        syringes=[
            Syringe(
                id=0,
                bioink="collagen_i_8mg_per_mL",
                cell_payload="general_mammalian",
                needle=needle,
                # Quarter-cube bbox — 5x5x2 chunk in the (+x, +y) corner.
                # Perimeter ratio vs full cube: 4*5 / 4*10 = 50% expected.
                region=RegionBBox(min=(0.0, 0.0, 0.0), max=(5.0, 5.0, 2.0)),
            ),
            Syringe(
                id=1,
                bioink="fibrin_25mg_per_mL",
                cell_payload="general_mammalian",
                needle=needle,
                region=RegionAll(),
            ),
        ],
        slicing=SlicingParams(
            layer_height_mm=0.5,
            line_width_mm=0.5,
            print_speed_mm_per_min=120.0,
        ),
    )
    result = Slicer(profile=load_profile("hypothetical_3axis"), recipe=recipe).slice(mesh)
    extrusion_by_syringe: dict[int, float] = result.total_bioink_uL_by_syringe
    # Syringe 1 (RegionAll) deposits over the full mesh perimeter.
    full = extrusion_by_syringe[1]
    # Syringe 0 (quarter-bbox) — perimeter ratio is 4*5/4*10 = 0.5.
    quarter = extrusion_by_syringe[0]
    assert 0 < quarter < full
    # Within ±25% of half: 0.375..0.625 of full.
    assert 0.375 * full < quarter < 0.625 * full, (
        f"quarter-bbox syringe should deposit ~half full (got {quarter:.3f} vs {full:.3f})"
    )
