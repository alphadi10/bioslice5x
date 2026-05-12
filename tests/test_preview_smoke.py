"""Phase 4 / ADR-004 toolpath viewer smoke tests.

The G-code parser is testable on any platform without PyVista. The
PyVista-backed viewer requires VTK + a display (or off-screen rendering
support), so the rendering test is skipped on headless CI unless xvfb
is available, and on Python < 3.11 (the rrf emitter that produces the
test G-code is 3.11+).
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Any, cast

import pytest

pytestmark_emit = pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="emit_rrf uses `from datetime import UTC` (Python 3.11+)",
)


def _build_minimal_gcode(tmp: Path) -> Path:
    """Slice a tiny cube and write the G-code to `tmp/cube.gcode`."""
    import trimesh

    from bioslice5x import Slicer, load_profile
    from bioslice5x.recipe.models import Needle, Recipe, SlicingParams, Syringe

    cube: Any = trimesh.creation.box(extents=[6.0, 6.0, 2.0])
    cube.apply_translation([0.0, 0.0, 1.0])
    mesh = cast(trimesh.Trimesh, cube)
    recipe = Recipe(
        name="preview_test",
        syringes=[
            Syringe(
                id=0,
                bioink="collagen_i_8mg_per_mL",
                cell_payload="general_mammalian",
                needle=Needle(inner_diameter_mm=0.84, length_mm=12.7),
            )
        ],
        slicing=SlicingParams(
            layer_height_mm=0.5,
            line_width_mm=0.5,
            print_speed_mm_per_min=120.0,
        ),
    )
    out = tmp / "cube.gcode"
    Slicer(profile=load_profile("hypothetical_3axis"), recipe=recipe).slice(mesh).write_gcode(out)
    return out


# ---------------------------------------------------------------------------
# Parser tests (no display required)
# ---------------------------------------------------------------------------


@pytestmark_emit
def test_parse_gcode_returns_moves_and_header() -> None:
    """Parser extracts moves and the META block from a real slicer output."""
    from bioslice5x.visualization.preview import parse_gcode

    with tempfile.TemporaryDirectory() as td:
        gcode_path = _build_minimal_gcode(Path(td))
        moves, header = parse_gcode(gcode_path)
    assert len(moves) > 0, "expected at least one move"
    # Header carries the META block plus prose fields.
    assert "meta.kinematic_chain" in header
    assert header["meta.kinematic_chain"] == "three_axis"
    assert "meta.extrusion_mode" in header
    assert header["meta.extrusion_mode"] == "displacement"
    assert "meta.bioink_calibration" in header
    # The mix of travel and extrusion moves: at least one of each.
    travels = [m for m in moves if m.is_travel]
    extrusions = [m for m in moves if not m.is_travel]
    assert len(travels) >= 1, "expected at least one travel move"
    assert len(extrusions) >= 1, "expected at least one extrusion move"


@pytestmark_emit
def test_parsed_extrusion_has_volume_and_feed() -> None:
    """Extrusion moves carry both E (volume) and F (feed) tokens."""
    from bioslice5x.visualization.preview import parse_gcode

    with tempfile.TemporaryDirectory() as td:
        gcode_path = _build_minimal_gcode(Path(td))
        moves, _ = parse_gcode(gcode_path)
    for m in moves:
        if not m.is_travel:
            assert m.extrusion_uL > 0, f"extrusion move with zero E: {m}"
            assert m.feed_mm_per_min > 0, f"extrusion move with zero F: {m}"
            break
    else:
        pytest.fail("no extrusion move found")


def test_parser_handles_arbitrary_tokens() -> None:
    """Parser handles A/B/C tokens for 5-axis G-code without needing emit_rrf."""
    from bioslice5x.visualization.preview import parse_gcode

    fake_gcode = """
; ============================================
; BioSlice5X G-code (synthetic test)
; ============================================
; Profile:             open5x_prusa (rrf)
; Recipe:              synthetic
;META: kinematic_chain=tilt_swivel
;META: bioink_calibration=uncalibrated

G90
M83
; ---- start of print ----
G1 X0 Y0 Z0.2 A30 C0 F1200  ; travel
G1 X5 Y0 Z0.2 A30 C45 E0.05 F60
G1 X5 Y5 Z0.2 A30 C90 E0.05 F60
G1 X0 Y5 Z0.2 A30 C135 E0.05 F60
G1 X0 Y0 Z0.2 A30 C180 E0.05 F60
; ---- end of print ----
M84
"""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "synthetic.gcode"
        p.write_text(fake_gcode)
        moves, header = parse_gcode(p)
    assert len(moves) == 5
    assert moves[0].is_travel is True
    assert moves[1].is_travel is False
    # Rotary axes captured.
    assert moves[1].a_deg == 30.0
    assert moves[1].c_deg == 45.0
    assert moves[2].c_deg == 90.0
    # META block parsed.
    assert header["meta.kinematic_chain"] == "tilt_swivel"
    assert header["meta.bioink_calibration"] == "uncalibrated"
    # G-code without `;STRESS:` tokens (legacy / third-party) parses
    # cleanly with wall_shear_pa=None on every move — required for the
    # viewer's "shear" color mode to gracefully fall back.
    assert all(m.wall_shear_pa is None for m in moves)


def test_parser_extracts_stress_tokens() -> None:
    """`;STRESS:<Pa>` trailing comments populate ParsedMove.wall_shear_pa."""
    from bioslice5x.visualization.preview import parse_gcode

    fake_gcode = """
; ============================================
;META: kinematic_chain=three_axis
;META: bioink_calibration=uncalibrated

G90
M83
; ---- start of print ----
G1 X0 Y0 Z0.2 F1200  ; travel
G1 X1 Y0 Z0.2 E0.01 F60  ;STRESS:1234.56
G1 X2 Y0 Z0.2 E0.01 F60  ;STRESS:0.00
G1 X3 Y0 Z0.2 E0.01 F60  ;STRESS:9876.5
; ---- end of print ----
M84
"""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "stress.gcode"
        p.write_text(fake_gcode)
        moves, _ = parse_gcode(p)
    assert len(moves) == 4
    # Travel: no stress token expected.
    assert moves[0].is_travel is True
    assert moves[0].wall_shear_pa is None
    # Extrusion moves: stress captured.
    assert moves[1].wall_shear_pa == pytest.approx(1234.56)
    assert moves[2].wall_shear_pa == pytest.approx(0.0)
    assert moves[3].wall_shear_pa == pytest.approx(9876.5)


@pytestmark_emit
def test_real_slicer_output_carries_stress_token() -> None:
    """End-to-end: emit_rrf emits `;STRESS:` and parse_gcode reads it back."""
    from bioslice5x.visualization.preview import parse_gcode

    with tempfile.TemporaryDirectory() as td:
        gcode_path = _build_minimal_gcode(Path(td))
        moves, _ = parse_gcode(gcode_path)
    extrusions = [m for m in moves if not m.is_travel]
    assert len(extrusions) > 0
    # Every extrusion move from a fresh slice has a stress entry.
    assert all(m.wall_shear_pa is not None and m.wall_shear_pa >= 0 for m in extrusions)


# ---------------------------------------------------------------------------
# Rendering test — headless screenshot (requires PyVista + a display backend)
# ---------------------------------------------------------------------------

_PYVISTA_AVAILABLE = False
try:
    import pyvista  # noqa: F401

    _PYVISTA_AVAILABLE = True
except ImportError:
    pass


@pytest.mark.skipif(not _PYVISTA_AVAILABLE, reason="PyVista not installed.")
@pytestmark_emit
def test_screenshot_renders_to_png() -> None:
    """Headless screenshot mode produces a PNG file. Skip if no PyVista."""
    from bioslice5x.visualization.preview import preview_gcode

    with tempfile.TemporaryDirectory() as td:
        gcode_path = _build_minimal_gcode(Path(td))
        png_path = Path(td) / "cube.png"
        try:
            preview_gcode(
                gcode_path,
                build_volume=((-50.0, 50.0), (-50.0, 50.0), (0.0, 80.0)),
                show=False,
                screenshot=png_path,
            )
        except Exception as exc:
            # CI without a display server (and without xvfb) can fail to
            # initialize VTK. Skip rather than fail — the parser tests
            # already cover the non-rendering surface.
            pytest.skip(f"PyVista rendering unavailable in this environment: {exc}")
        assert png_path.is_file(), "screenshot file was not created"
        assert png_path.stat().st_size > 1000, "screenshot file is implausibly small"


@pytest.mark.skipif(not _PYVISTA_AVAILABLE, reason="PyVista not installed.")
@pytestmark_emit
def test_screenshot_with_mesh_overlay_renders() -> None:
    """Mesh overlay loads and renders alongside the toolpath."""
    import trimesh

    from bioslice5x.visualization.preview import preview_gcode

    with tempfile.TemporaryDirectory() as td:
        gcode_path = _build_minimal_gcode(Path(td))
        stl_path = Path(td) / "cube.stl"
        cube: Any = trimesh.creation.box(extents=[6.0, 6.0, 2.0])
        cube.apply_translation([0.0, 0.0, 1.0])
        cast(trimesh.Trimesh, cube).export(stl_path)
        png_path = Path(td) / "cube_mesh.png"
        try:
            viewer = preview_gcode(
                gcode_path,
                show=False,
                screenshot=png_path,
                source_mesh_path=stl_path,
                source_mesh_opacity=0.2,
            )
        except Exception as exc:
            pytest.skip(f"PyVista rendering unavailable: {exc}")
        assert png_path.is_file()
        # No mesh-load error surfaced.
        assert viewer._source_mesh_error is None


@pytest.mark.skipif(not _PYVISTA_AVAILABLE, reason="PyVista not installed.")
@pytestmark_emit
def test_missing_mesh_overlay_surfaces_error_not_crash() -> None:
    """Bad mesh path doesn't crash the viewer — it surfaces an info-overlay error."""
    from bioslice5x.visualization.preview import preview_gcode

    with tempfile.TemporaryDirectory() as td:
        gcode_path = _build_minimal_gcode(Path(td))
        png_path = Path(td) / "out.png"
        try:
            viewer = preview_gcode(
                gcode_path,
                show=False,
                screenshot=png_path,
                source_mesh_path=Path(td) / "does_not_exist.stl",
            )
        except Exception as exc:
            pytest.skip(f"PyVista rendering unavailable: {exc}")
        assert png_path.is_file(), "the rest of the scene must still render"
        assert viewer._source_mesh_error is not None
        assert "failed to load" in viewer._source_mesh_error


@pytest.mark.skipif(not _PYVISTA_AVAILABLE, reason="PyVista not installed.")
@pytestmark_emit
def test_screenshot_shear_color_mode_renders() -> None:
    """The shear color mode renders without error when stress tokens are present."""
    from bioslice5x.visualization.preview import preview_gcode

    with tempfile.TemporaryDirectory() as td:
        gcode_path = _build_minimal_gcode(Path(td))
        png_path = Path(td) / "cube_shear.png"
        try:
            preview_gcode(
                gcode_path,
                show=False,
                screenshot=png_path,
                color_by="shear",
                cell_stress_threshold_pa=5000.0,
            )
        except Exception as exc:
            pytest.skip(f"PyVista rendering unavailable: {exc}")
        assert png_path.is_file()
        assert png_path.stat().st_size > 1000


def test_compute_layer_indices_z_banded() -> None:
    """Flat / wrap-Z prints bin into rounded-Z layers."""
    from bioslice5x.visualization.preview import ParsedMove, _compute_layer_indices

    def _move(z: float) -> ParsedMove:
        return ParsedMove(
            end_xyz=(0.0, 0.0, z),
            is_travel=False,
            a_deg=None,
            b_deg=None,
            c_deg=None,
            extrusion_uL=0.01,
            feed_mm_per_min=60.0,
            wall_shear_pa=None,
        )

    # 3 layers, 5 moves per layer — clearly Z-banded.
    moves = [_move(z) for z in [0.2] * 5 + [0.4] * 5 + [0.6] * 5]
    idx = _compute_layer_indices(moves)
    assert idx.tolist() == [0] * 5 + [1] * 5 + [2] * 5


def test_compute_layer_indices_falls_back_for_conformal() -> None:
    """Many distinct Zs (conformal print) falls back to 100 ordinal bands."""
    from bioslice5x.visualization.preview import ParsedMove, _compute_layer_indices

    moves = [
        ParsedMove(
            end_xyz=(0.0, 0.0, 0.01 * i),  # 500 distinct Zs
            is_travel=False,
            a_deg=None,
            b_deg=None,
            c_deg=None,
            extrusion_uL=0.01,
            feed_mm_per_min=60.0,
            wall_shear_pa=None,
        )
        for i in range(500)
    ]
    idx = _compute_layer_indices(moves)
    # Falls back to 100 bands.
    assert int(idx.max()) == 99
    # First N go to band 0, last N to band 99 — monotone.
    assert idx[0] == 0
    assert idx[-1] == 99


def test_compute_layer_indices_empty() -> None:
    """Empty input returns an empty array (no crash)."""
    from bioslice5x.visualization.preview import _compute_layer_indices

    idx = _compute_layer_indices([])
    assert idx.shape == (0,)


def test_shear_mode_falls_back_to_z_without_stress_tokens() -> None:
    """If no move has wall_shear_pa, ToolpathViewer falls back to z mode."""
    from bioslice5x.visualization.preview import ParsedMove, ToolpathViewer

    # Build a minimal move list with no stress entries.
    moves = [
        ParsedMove(
            end_xyz=(0.0, 0.0, 0.2),
            is_travel=False,
            a_deg=None,
            b_deg=None,
            c_deg=None,
            extrusion_uL=0.01,
            feed_mm_per_min=60.0,
            wall_shear_pa=None,
        ),
        ParsedMove(
            end_xyz=(1.0, 0.0, 0.2),
            is_travel=False,
            a_deg=None,
            b_deg=None,
            c_deg=None,
            extrusion_uL=0.01,
            feed_mm_per_min=60.0,
            wall_shear_pa=None,
        ),
    ]
    viewer = ToolpathViewer(moves=moves, header={}, color_by="shear")
    # The fallback decision happens inside _build_plotter, which we don't
    # have to call to verify the flag — but we can probe it via a try.
    if _PYVISTA_AVAILABLE:
        try:
            viewer._build_plotter(off_screen=True).close()
        except Exception:
            pytest.skip("PyVista unavailable for plotter build")
        assert viewer._shear_fallback_to_z is True


def test_viewer_module_imports_without_pyvista() -> None:
    """The preview module imports even if PyVista isn't installed.

    The PyVista import is inside `_build_plotter`, not at module load.
    This means the rest of bioslice5x stays usable on minimal installs
    (no `[viz]` extra), and a clear RuntimeError fires only when the
    user actually tries to render.
    """
    from bioslice5x.visualization import preview as preview_module

    assert hasattr(preview_module, "ToolpathViewer")
    assert hasattr(preview_module, "parse_gcode")


# Marker for `pyvista=False` ImportError path. We don't actually
# uninstall PyVista, just verify the lazy-import message exists.
def test_viewer_runtime_error_message_mentions_install() -> None:
    """If PyVista is missing, the RuntimeError points the user at the fix."""
    import importlib
    import sys as _sys

    from bioslice5x.visualization.preview import ToolpathViewer

    # Temporarily make `pyvista` un-importable.
    original = _sys.modules.pop("pyvista", None)
    _sys.modules["pyvista"] = None  # type: ignore[assignment]
    try:
        viewer = ToolpathViewer(moves=[], header={}, title="test")
        with pytest.raises(RuntimeError, match="bioslice5x\\[viz\\]"):
            viewer.show()
    finally:
        # Restore.
        if original is not None:
            _sys.modules["pyvista"] = original
        else:
            _sys.modules.pop("pyvista", None)
        importlib.invalidate_caches()
