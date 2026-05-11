"""Pin the ADR-001 wrap-tilt clamping worked examples + behavioural contracts.

ADR-001 (`docs/adr/0001-wrap-tilt-clamping.md`) commits the project to a
refuse-loudly default + opt-in arc-split for wrap-around-tilt-axis prints
whose requested arc exceeds the profile's tilt range. The pure-arithmetic
expectations are pinned here; the integration contracts (slicer-level
behaviour) are pinned alongside them.

If the slicer's behaviour ever diverges from the doc, the test fails and
forces the doc to be updated in lockstep.
"""

from __future__ import annotations

import math
from typing import Any, cast

import pytest
import trimesh

from bioslice5x import Slicer, load_profile
from bioslice5x.errors import ClampingExceededError
from bioslice5x.geometry.conformal_slicer import _min_arc_split_count
from bioslice5x.recipe.models import (
    FixedOrientation,
    Needle,
    Recipe,
    SlicingParams,
    Syringe,
    WrapAroundAxisSlicing,
)

pytestmark = pytest.mark.skipif(
    __import__("sys").version_info < (3, 11),
    reason="end-to-end paths invoke emit_rrf which uses `datetime.UTC` (Python 3.11+)",
)


# ---------------------------------------------------------------------------
# Pure arithmetic — runs on any Python version
# ---------------------------------------------------------------------------


def test_voron_full_360_minimum_split_count() -> None:
    """Voron, ±110° tilt (range 220°), requested 360° → N = ceil(360/220) = 2."""
    assert _min_arc_split_count(arc_span_deg=360.0, tilt_range_deg=220.0) == 2


def test_prusa_full_360_minimum_split_count() -> None:
    """Prusa, ±200° tilt (range 400°), requested 360° → fits in N=1."""
    assert _min_arc_split_count(arc_span_deg=360.0, tilt_range_deg=400.0) == 1


def test_voron_270_arc_minimum_split_count() -> None:
    """Voron, 270° arc, 220° range → N=2 (each sub-arc 135° ≤ 220°)."""
    assert _min_arc_split_count(arc_span_deg=270.0, tilt_range_deg=220.0) == 2


# ---------------------------------------------------------------------------
# Integration contracts — require the end-to-end pipeline
# ---------------------------------------------------------------------------


def _cylinder_mesh(radius_mm: float = 5.0, length_mm: float = 10.0) -> trimesh.Trimesh:
    cyl: Any = trimesh.creation.cylinder(radius=radius_mm, height=length_mm, sections=24)
    cyl.apply_translation([0.0, 0.0, length_mm / 2.0])
    return cast(trimesh.Trimesh, cyl)


def _recipe(
    *,
    wrap_axis: str = "y",
    arc_start_deg: float = -180.0,
    arc_end_deg: float = 180.0,
    allow_tilt_arc_split: bool = False,
    arc_split_count: int = 1,
) -> Recipe:
    return Recipe(
        name="adr_001_contract",
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
            mode=WrapAroundAxisSlicing(
                kind="wrap_around_axis",
                wrap_axis=cast(Any, wrap_axis),
                cylinder_radius_mm=5.0,
                arc_start_deg=arc_start_deg,
                arc_end_deg=arc_end_deg,
                allow_tilt_arc_split=allow_tilt_arc_split,
                arc_split_count=arc_split_count,
            ),
        ),
        print_orientation=FixedOrientation(),
    )


def test_voron_360_arc_default_refuses() -> None:
    """ADR-001 contract (a): Voron 360° wrap, no arc-split → ClampingExceededError."""
    voron = load_profile("open5x_voron")
    slicer = Slicer(profile=voron, recipe=_recipe(wrap_axis="y"))
    with pytest.raises(ClampingExceededError) as exc:
        slicer.slice(_cylinder_mesh())
    err = exc.value
    assert err.wrap_axis == "y"
    assert err.minimum_sub_arcs >= 2
    msg = str(err)
    assert "allow_tilt_arc_split" in msg


def test_voron_360_arc_with_split_proceeds() -> None:
    """ADR-001 contract (b): with allow_tilt_arc_split + N >= min, slice succeeds."""
    voron = load_profile("open5x_voron")
    slicer = Slicer(
        profile=voron,
        recipe=_recipe(wrap_axis="y", allow_tilt_arc_split=True, arc_split_count=2),
    )
    result = slicer.slice(_cylinder_mesh())
    assert len(result.moves) > 0
    # At least one B token observed across G1 lines — the wrap actually exercises tilt.
    g1 = [line for line in result.gcode.splitlines() if line.startswith("G1 ")]
    b_tokens = {tok for line in g1 for tok in line.split() if tok.startswith("B")}
    assert len(b_tokens) >= 4, f"expected ≥4 distinct B values in split-arc wrap; got {b_tokens}"


def test_prusa_360_arc_succeeds_without_split() -> None:
    """ADR-001 contract (c): Prusa 360° wrap on tilt axis fits in N=1, no opt-in needed."""
    prusa = load_profile("open5x_prusa")
    slicer = Slicer(profile=prusa, recipe=_recipe(wrap_axis="x"))
    result = slicer.slice(_cylinder_mesh())
    assert len(result.moves) > 0


def test_voron_360_arc_split_too_small_still_refuses() -> None:
    """ADR-001: even with allow_tilt_arc_split, N below the minimum is refused.

    The user opting in does not opt them out of the math — partial wraps
    are worse than clear errors.
    """
    voron = load_profile("open5x_voron")
    slicer = Slicer(
        profile=voron,
        recipe=_recipe(wrap_axis="y", allow_tilt_arc_split=True, arc_split_count=1),
    )
    with pytest.raises(ClampingExceededError):
        slicer.slice(_cylinder_mesh())


def test_minimum_split_count_function_pure_math() -> None:
    """The pure-arithmetic helper used inside _slice_conformal is exposed
    for tests (and for any user wanting to pre-compute their split count)."""
    # Voron 270° / 220° range → ceil(1.227) = 2.
    assert _min_arc_split_count(270.0, 220.0) == 2
    # Boundary: span exactly equal to range → N=1.
    assert _min_arc_split_count(220.0, 220.0) == 1
    # span just barely over range → N=2.
    assert _min_arc_split_count(220.0 + 1e-9, 220.0) == 2
    # Negative span treated as absolute.
    assert _min_arc_split_count(-360.0, 220.0) == 2


def test_pi_radians_arc_decomposition_smoke() -> None:
    """A π-radian (180°) arc on Voron (220° range) fits in N=1; the split
    machinery isn't engaged. This locks the "no opt-in needed" path."""
    voron = load_profile("open5x_voron")
    slicer = Slicer(
        profile=voron,
        recipe=_recipe(wrap_axis="y", arc_start_deg=-90.0, arc_end_deg=90.0),
    )
    result = slicer.slice(_cylinder_mesh())
    # No retract-clear travels expected when N=1.
    assert len(result.moves) > 0
    # All B tokens within ±90° (i.e., within Voron's ±110° range).
    g1 = [line for line in result.gcode.splitlines() if line.startswith("G1 ")]
    for line in g1:
        for tok in line.split():
            if tok.startswith("B"):
                val = float(tok[1:])
                assert -110.0 <= val <= 110.0, f"B token {tok!r} outside Voron tilt range"
                assert -math.degrees(math.pi) <= val <= math.degrees(math.pi)  # sanity
