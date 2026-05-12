"""Rectilinear infill in 2D parameter space — flat-and-curved unified.

Per ADR-002, infill in v0.1.0 is **rectilinear scan-lines** at a
configurable base angle, alternating 90° per layer.

The scan-line generator is generic over 2D polygons: it doesn't know
whether the polygon coordinates are (x, y) on a flat layer or (s, θ) on a
conformal layer. The caller provides a "lift" function that maps a
2D parameter-space point back to a machine-frame Point3D + JointAngles.

This is the unified general-form principle from the project's
architectural rules: one scan-line generator, two callers (flat and
conformal), no duplicate implementations.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

from shapely.geometry import LineString, MultiLineString, MultiPolygon, Polygon
from shapely.ops import unary_union

from bioslice5x.geometry.types import Polygon2D
from bioslice5x.kinematics.canonical import JointAngles
from bioslice5x.pathing.types import Move, Point3D
from bioslice5x.recipe.models import SlicingParams

LiftFn = Callable[[tuple[float, float]], tuple[Point3D, JointAngles | None]]


def _shapely_polygon_with_holes(
    polygons: list[Polygon2D],
) -> Polygon | MultiPolygon | None:
    """Convert a list of Polygon2D (exteriors + holes) to a shapely polygon."""
    if not polygons:
        return None
    # Treat the first exterior + all subsequent holes as a single polygon.
    # For the v0.1.0 flat-cube case this is just one exterior + zero holes.
    exteriors = [p for p in polygons if not p.is_hole]
    holes = [p for p in polygons if p.is_hole]
    if not exteriors:
        return None
    # Build one polygon per exterior; subtract any holes that lie within it.
    polys: list[Polygon] = []
    for ext in exteriors:
        ext_pts = list(ext.points)
        ext_poly = Polygon(ext_pts)
        ext_holes = [list(h.points) for h in holes if Polygon(h.points).within(ext_poly)]
        polys.append(Polygon(ext_pts, holes=ext_holes))
    if len(polys) == 1:
        return polys[0]
    return MultiPolygon(polys)


def rectilinear_scan_segments(
    polygons: list[Polygon2D],
    *,
    angle_rad: float,
    spacing_mm: float,
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Generate clipped 2D scan-line segments through the input polygons.

    The unified general-form scan-line generator. Caller is responsible
    for lifting the returned 2D coordinates into machine-frame Point3D +
    joints — for flat layers, the lift is identity-with-fixed-orientation;
    for conformal layers, the lift uses the kinematic chain.

    Returns a list of (start_xy, end_xy) tuples. Each segment is a clipped
    line entirely inside the polygon.
    """
    shape = _shapely_polygon_with_holes(polygons)
    if shape is None or shape.is_empty:
        return []
    # Bounding circle radius — scan-lines just need to extend past the
    # polygon's farthest extent before clipping.
    minx, miny, maxx, maxy = shape.bounds
    cx = (minx + maxx) / 2.0
    cy = (miny + maxy) / 2.0
    radius = math.hypot(maxx - minx, maxy - miny)  # diagonal
    # Direction along the scan-lines, and perpendicular (where we step).
    dir_x = math.cos(angle_rad)
    dir_y = math.sin(angle_rad)
    perp_x = -dir_y
    perp_y = dir_x
    # Generate scan-line offsets in the perpendicular direction.
    # ADR-002 worked example: offsets are gap-centred, not boundary-flush
    # — each scan-line sits in the middle of its allocated band so that no
    # line lands exactly on the polygon boundary. For a 10mm square at
    # spacing 2.5mm, this produces 4 lines at y ≈ ±1.25, ±3.75.
    n_lines = max(1, math.ceil(radius / spacing_mm))
    offsets = [(i - n_lines + 0.5) * spacing_mm for i in range(2 * n_lines)]
    if not offsets:
        return []
    # Batch every scan-line into a single MultiLineString and clip
    # against the shape in one call. The audit profiler observed
    # `shape.intersection` as 1,140 calls/slice on the chips reference
    # mesh — Shapely / GEOS handles a single multigeom intersection
    # noticeably faster than N sequential ones, and the Python dispatch
    # overhead per call drops to one.
    lines: list[LineString] = []
    for offset in offsets:
        center_x = cx + offset * perp_x
        center_y = cy + offset * perp_y
        far = radius
        lines.append(
            LineString(
                [
                    (center_x - far * dir_x, center_y - far * dir_y),
                    (center_x + far * dir_x, center_y + far * dir_y),
                ]
            )
        )
    multi = MultiLineString(lines)
    clipped = shape.intersection(multi)
    if clipped.is_empty:
        return []
    # `clipped` may be LineString, MultiLineString, or
    # GeometryCollection depending on how the shape clipped each line.
    if isinstance(clipped, LineString):
        geom_iter: list[Any] = [clipped]
    elif isinstance(clipped, MultiLineString):
        geom_iter = list(clipped.geoms)
    else:
        # GeometryCollection — pull every LineString / MultiLineString
        # member; skip points / polygons that fell out of degenerate
        # intersections.
        geom_iter = []
        for g in getattr(clipped, "geoms", []):
            if isinstance(g, LineString):
                geom_iter.append(g)
            elif isinstance(g, MultiLineString):
                geom_iter.extend(g.geoms)
    segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for ls in geom_iter:
        coords = list(ls.coords)
        if len(coords) < 2:
            continue
        start = (float(coords[0][0]), float(coords[0][1]))
        end = (float(coords[-1][0]), float(coords[-1][1]))
        segments.append((start, end))
    return segments


def _density_to_spacing_mm(density: float, line_width_mm: float) -> float:
    """Convert a density in (0, 1] to scan-line spacing.

    density = 1.0 → spacing = line_width (solid).
    density = 0.5 → spacing = 2 × line_width.
    density = 0.2 → spacing = 5 × line_width.
    """
    if density <= 0:
        raise ValueError("density must be positive (use the perimeter-only path for 0.0)")
    return line_width_mm / density


def generate_infill_moves(
    polygons: list[Polygon2D],
    *,
    syringe_id: int,
    slicing: SlicingParams,
    layer_index: int,
    lift: LiftFn,
    start_point: Point3D,
) -> tuple[list[Move], Point3D]:
    """Build extrusion Moves for one layer's infill.

    `lift` maps a 2D parameter-space point to (Point3D, JointAngles|None).
    For flat layers, the lift attaches a fixed z and the recipe's joints.
    For conformal layers, the lift goes through the kinematic chain.

    Returns (moves, last_point) so the caller can chain into the next
    layer or perimeter pass.
    """
    if slicing.infill_density <= 0:
        return [], start_point
    angle_rad = math.radians(slicing.infill_angle_deg + 90.0 * (layer_index % 2))
    spacing = _density_to_spacing_mm(slicing.infill_density, slicing.line_width_mm)
    segments_2d = rectilinear_scan_segments(polygons, angle_rad=angle_rad, spacing_mm=spacing)
    if not segments_2d:
        return [], start_point
    moves: list[Move] = []
    current = start_point
    volume_per_mm_uL = slicing.line_width_mm * slicing.layer_height_mm
    extrude_feed = slicing.print_speed_mm_per_min
    travel_feed = slicing.travel_speed_mm_per_min * slicing.travel_speed_reduction_in_bath
    for seg_idx, (a_2d, b_2d) in enumerate(segments_2d):
        a_pt, a_joints = lift(a_2d)
        b_pt, b_joints = lift(b_2d)
        # Travel to the segment start.
        if current != a_pt:
            moves.append(
                Move(
                    start=current,
                    end=a_pt,
                    syringe_id=syringe_id,
                    is_travel=True,
                    extrusion_volume_uL=0.0,
                    feed_mm_per_min=travel_feed,
                    segment_id=f"L{layer_index:04d}_I{seg_idx:04d}_T",
                    joints=a_joints,
                )
            )
            current = a_pt
        # Extrude.
        length = current.distance_to(b_pt)
        if length > 0:
            moves.append(
                Move(
                    start=current,
                    end=b_pt,
                    syringe_id=syringe_id,
                    is_travel=False,
                    extrusion_volume_uL=length * volume_per_mm_uL,
                    feed_mm_per_min=extrude_feed,
                    segment_id=f"L{layer_index:04d}_I{seg_idx:04d}_E",
                    joints=b_joints,
                )
            )
            current = b_pt
    return moves, current


def flat_lift_factory(z: float, joints: JointAngles | None) -> LiftFn:
    """Construct a `LiftFn` for flat layers: 2D (x, y) → 3D (x, y, z) + joints."""

    def _lift(xy: tuple[float, float]) -> tuple[Point3D, JointAngles | None]:
        return Point3D(xy[0], xy[1], z), joints

    return _lift


__all__ = [
    "LiftFn",
    "flat_lift_factory",
    "generate_infill_moves",
    "rectilinear_scan_segments",
]


# Suppress the unused import warning for `unary_union` — exposed for future
# use when combining adjacent perimeter offsets with infill bounds.
_ = unary_union
