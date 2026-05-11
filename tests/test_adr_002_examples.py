"""Pin the ADR-002 worked example.

The default infill pattern is rectilinear with 90° layer alternation. The
worked example in `docs/adr/0002-default-infill-pattern.md` claims a 10mm
square at 20% density produces four horizontal scan-lines at y = -3.75,
-1.25, +1.25, +3.75, each ≈ 10 mm long, total ≈ 40 mm.

This test re-derives those numbers from `rectilinear_scan_segments`. If
the algorithm changes, either the test or the doc must be updated in
lockstep.
"""

from __future__ import annotations

import math

import pytest

from bioslice5x.geometry.types import Polygon2D
from bioslice5x.pathing.infill import _density_to_spacing_mm, rectilinear_scan_segments


def _square(side_mm: float = 10.0) -> list[Polygon2D]:
    half = side_mm / 2.0
    return [
        Polygon2D(
            z=0.0,
            points=(
                (-half, -half),
                (half, -half),
                (half, half),
                (-half, half),
            ),
            is_hole=False,
        )
    ]


def test_density_to_spacing_at_20_percent() -> None:
    """density 0.2 with line_width 0.5 → spacing 2.5 mm. ADR-002 §worked example."""
    assert _density_to_spacing_mm(0.2, 0.5) == pytest.approx(2.5, rel=1e-9)


def test_rectilinear_scanlines_on_10mm_square_at_20_percent() -> None:
    """Four horizontal scan-lines at y ≈ ±1.25, ±3.75, each 10 mm long.

    Note: the exact y values depend on the scan-line generator's offset
    sweep around the polygon centroid. The test asserts the structural
    properties from ADR-002: 4 segments, each ~10 mm long, spaced ~2.5 mm
    apart, all horizontal (constant-y endpoints).
    """
    segments = rectilinear_scan_segments(_square(10.0), angle_rad=0.0, spacing_mm=2.5)
    # Filter out any zero-length artifacts on the polygon boundary.
    real = [s for s in segments if math.hypot(s[1][0] - s[0][0], s[1][1] - s[0][1]) > 1e-6]
    assert len(real) == 4, f"expected 4 scan-lines on a 10mm square, got {len(real)}: {real}"
    for start, end in real:
        # Horizontal: y values match.
        assert abs(start[1] - end[1]) < 1e-6, f"non-horizontal scan-line {start} → {end}"
        # Each line spans the full square width.
        length = math.hypot(end[0] - start[0], end[1] - start[1])
        assert length == pytest.approx(10.0, abs=1e-6), f"expected 10mm length, got {length}"
    # The y values are roughly at ±1.25 and ±3.75 — the worked-example claim.
    ys = sorted({round(s[0][1], 3) for s in real})
    assert ys == [-3.75, -1.25, 1.25, 3.75], f"unexpected y positions: {ys}"


def test_rectilinear_scanlines_at_45_degrees() -> None:
    """45° scan-lines on a 10mm square produce diagonal segments; the
    total infill length differs from horizontal but is still finite."""
    segments = rectilinear_scan_segments(
        _square(10.0), angle_rad=math.radians(45.0), spacing_mm=2.5
    )
    real = [s for s in segments if math.hypot(s[1][0] - s[0][0], s[1][1] - s[0][1]) > 1e-6]
    assert len(real) > 0
    for start, end in real:
        # 45° lines have equal dx and dy magnitudes (within numerical noise).
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        assert abs(abs(dx) - abs(dy)) < 1e-6, f"non-45° segment: dx={dx} dy={dy}"


def test_density_zero_raises() -> None:
    """The density-to-spacing conversion only valid for positive density."""
    with pytest.raises(ValueError, match="positive"):
        _density_to_spacing_mm(0.0, 0.5)


def test_solid_infill_density_one_uses_line_width_spacing() -> None:
    """density 1.0 → spacing = line_width (every pass adjacent to the next)."""
    assert _density_to_spacing_mm(1.0, 0.5) == 0.5
