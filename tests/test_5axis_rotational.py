"""Regression lock for multilayer 5-axis rotational slicing.

Tests the vascular-scaffold pipeline: tall thin-walled cylinder →
conformal `wrap_around_axis` slicing on an Open5X Prusa profile →
G-code with `A` and `C` tokens on every extrusion move, precise to 4
decimals, with the right axial spacing and full-revolution C sweeps.

Backs `scripts/verify_5axis_gcode.py` — the same checks the standalone
verifier runs, run automatically in CI so changes to the kinematic
chain or the postprocessor's letter mapping can't silently break 5-axis
precision.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any, cast

import pytest
import trimesh

pytestmark = pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="emit_rrf uses `from datetime import UTC` (Python 3.11+)",
)

# Make `scripts/` importable so the same verifier the CLI uses runs here too.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from verify_5axis_gcode import verify  # noqa: E402

from bioslice5x import Slicer, load_profile  # noqa: E402
from bioslice5x.recipe.models import (  # noqa: E402
    Needle,
    Recipe,
    SlicingParams,
    Syringe,
    WrapAroundAxisSlicing,
)


def _vascular_scaffold(radius_mm: float = 5.0, height_mm: float = 20.0) -> trimesh.Trimesh:
    """Tall thin cylinder — the vascular-scaffold rotational fixture."""
    cyl: Any = trimesh.creation.cylinder(radius=radius_mm, height=height_mm, sections=96)
    cyl.apply_translation([0.0, 0.0, height_mm / 2.0])
    return cast(trimesh.Trimesh, cyl)


def _vascular_recipe() -> Recipe:
    """22G + collagen, full 360° wrap around z, 0.4 mm axial layers."""
    return Recipe(
        name="vascular_scaffold_test",
        syringes=[
            Syringe(
                id=0,
                bioink="collagen_i_8mg_per_mL",
                cell_payload="general_mammalian",
                needle=Needle(inner_diameter_mm=0.41, length_mm=12.7, gauge_label="22G"),
            )
        ],
        slicing=SlicingParams(
            layer_height_mm=0.4,
            line_width_mm=0.4,
            print_speed_mm_per_min=60.0,
            travel_speed_mm_per_min=600.0,
            infill_density=0.0,
            mode=WrapAroundAxisSlicing(
                wrap_axis="z",
                cylinder_radius_mm=5.0,
                arc_start_deg=-180.0,
                arc_end_deg=180.0,
            ),
        ),
    )


def _slice_vascular() -> str:
    mesh = _vascular_scaffold(5.0, 20.0)
    result = Slicer(profile=load_profile("open5x_prusa"), recipe=_vascular_recipe()).slice(mesh)
    return result.gcode


def test_rotational_gcode_passes_all_5axis_precision_checks() -> None:
    """Run the full verifier — every check must pass.

    The verifier covers axis tokens, finiteness, layer-fixed A,
    layer-swept C, axial Z spacing, layer count, decimal precision, and
    radial geometry. Any single check failing trips this test, so
    regressions surface specifically rather than as a vague "G-code
    looks wrong."
    """
    gcode = _slice_vascular()
    report = verify(
        gcode,
        wrap_axis="z",
        expected_radius_mm=5.0,
        expected_axial_extent_mm=20.0,
        layer_height_mm=0.4,
        arc_span_deg=360.0,
        arc_span_tolerance_deg=60.0,
        max_decimals=4,
    )
    if not report.all_passed():
        pytest.fail("\n" + report.render())


def test_rotational_gcode_emits_50_layers_and_full_revolutions() -> None:
    """Direct checks on the headline numbers — 50 layers, ~360° per layer."""
    gcode = _slice_vascular()
    report = verify(
        gcode,
        wrap_axis="z",
        expected_radius_mm=5.0,
        expected_axial_extent_mm=20.0,
        layer_height_mm=0.4,
    )
    assert report.summary["axial_layers"] == 50, (
        f"expected 50 axial layers (20 mm / 0.4 mm); got {report.summary['axial_layers']}"
    )
    c_mean = float(cast(str, report.summary["C_span_mean_deg"]))
    # Slicer samples at `line_width_mm` intervals around the
    # circumference, leaving a small seam gap. 320° is a conservative
    # lower bound that catches "the C sweep is broken" but allows the
    # normal seam discretization (~14° at line_width=0.4 mm, r=5 mm).
    assert c_mean > 320, f"C sweep too small: {c_mean}°"


def test_rotational_endpoints_lie_on_the_cylinder() -> None:
    """Every extrusion endpoint should sit at r ≈ cylinder_radius_mm in the XY plane.

    This is the geometric correctness check — if the kinematic transform
    drifts or the postprocessor flips a sign, endpoints will land off
    the cylinder surface. The verifier already covers this; the explicit
    test surfaces it as a labelled failure mode.
    """
    import tempfile

    from bioslice5x.visualization.preview import parse_gcode

    gcode = _slice_vascular()
    with tempfile.NamedTemporaryFile("w", suffix=".gcode", delete=False) as f:
        f.write(gcode)
        path = Path(f.name)
    try:
        moves, _ = parse_gcode(path)
    finally:
        path.unlink(missing_ok=True)

    extrusions = [m for m in moves if not m.is_travel]
    assert len(extrusions) > 0, "no extrusion moves emitted"
    deviations = [abs(math.hypot(m.end_xyz[0], m.end_xyz[1]) - 5.0) for m in extrusions]
    max_dev = max(deviations)
    assert max_dev < 0.01, (
        f"endpoints drift off the 5 mm cylinder by up to {max_dev:.4f} mm "
        f"(tolerance 0.01 mm). Likely a kinematic-transform or postprocessor bug."
    )


def test_rotational_meta_block_carries_kinematic_chain() -> None:
    """The G-code header's ;META: block must announce the 5-axis chain."""
    gcode = _slice_vascular()
    assert ";META: kinematic_chain=tilt_swivel" in gcode, (
        "5-axis G-code must carry kinematic_chain=tilt_swivel in the META "
        "block so machine consumers can refuse 3-axis-only firmware."
    )


def test_rotational_a_and_c_letters_match_open5x_prusa() -> None:
    """On open5x_prusa the tilt letter is A and the swivel letter is C.

    Locking the letter mapping catches profile-loader regressions that
    would silently emit B+C (Voron) tokens for a Prusa-targeted print.
    """
    gcode = _slice_vascular()
    # Pick one extrusion line and verify it carries both A and C, not B.
    for line in gcode.splitlines():
        if line.startswith("G1") and " E" in line:
            toks = line.split()
            letters = {t[0] for t in toks if t and t[0].isalpha()}
            assert "A" in letters, f"no A token on Prusa profile: {line!r}"
            assert "C" in letters, f"no C token on Prusa profile: {line!r}"
            assert "B" not in letters, (
                f"unexpected B token (Voron) on Prusa-profile output: {line!r}"
            )
            return
    pytest.fail("no extrusion G1 line found")
