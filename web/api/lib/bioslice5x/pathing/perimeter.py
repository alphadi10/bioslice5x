"""Perimeter extraction — Phase 2a baseline, 2b kinematic-transformed.

One extrusion pass around each closed polygon, in input order. No offsetting,
no infill, no travel optimization — the point of Phase 2a/2b is validating
the pipeline shape (2a) and the kinematic transform (2b), not path quality.
Infill lands in Phase 2c and is designed to work on flat and curved layers
through the same call path.

Pipeline:
1. The flat slicer produces layer polygons in **part frame** (z = layer
   height, x/y in mesh coords).
2. This module applies `kinematic_chain.part_to_machine(vertex, joints)`
   to each polygon vertex, producing machine-frame coordinates.
3. Each `Move` carries the canonical `joints` (or `None` for 3-axis) so the
   postprocessor can render the right axis-letter tokens.

For 3-axis chains the transform is the identity and `joints` is `None`.
"""

from __future__ import annotations

from bioslice5x.geometry.types import LayerGeometry
from bioslice5x.kinematics.canonical import JointAngles
from bioslice5x.kinematics.chain import KinematicChain
from bioslice5x.pathing.types import Move, Point3D
from bioslice5x.recipe.models import SlicingParams


def _segment_id(layer_idx: int, poly_idx: int, edge_idx: int, kind: str) -> str:
    return f"L{layer_idx:04d}_P{poly_idx:03d}_E{edge_idx:04d}_{kind}"


def _transform_vertex(
    part_xy: tuple[float, float],
    part_z: float,
    chain: KinematicChain,
    joints: JointAngles,
) -> Point3D:
    machine = chain.part_to_machine((part_xy[0], part_xy[1], part_z), joints)
    return Point3D(machine[0], machine[1], machine[2])


def generate_perimeter_paths(
    layers: list[LayerGeometry],
    syringe_id: int,
    slicing: SlicingParams,
    *,
    kinematic_chain: KinematicChain,
    joints: JointAngles | None = None,
    start_position: Point3D | None = None,
) -> list[Move]:
    """Build a flat list of extrusion + travel moves from layered polygons.

    For 3-axis profiles, pass `joints=None`; the chain is `ThreeAxisKinematics`
    and the transform is the identity. For tilt_swivel profiles, pass a
    fixed `JointAngles` — the same joints are attached to every move (2b
    fixed orientation; 2c+ extends to per-layer/per-segment variation).

    Volume per millimetre of extrusion is `line_width × layer_height` (with
    cross-section area = w·h and 1 mm³ = 1 µL of bioink). Note: length here
    is the **machine-frame** distance after transform; for tilt_swivel with
    non-zero tilt, that is the same as the part-frame distance because
    rotations preserve Euclidean distances.
    """
    volume_per_mm_uL = slicing.line_width_mm * slicing.layer_height_mm
    extrude_feed = slicing.print_speed_mm_per_min
    travel_feed = slicing.travel_speed_mm_per_min * slicing.travel_speed_reduction_in_bath
    # joints used both for the transform call and for the Move's metadata.
    # If the user passes joints=None on a tilt_swivel chain, treat that as
    # "zero rotation"; the kinematic transform handles it but the Move's
    # joints field stays None so the postprocessor knows not to emit A/C.
    transform_joints = joints if joints is not None else JointAngles(0.0, 0.0)

    current = start_position if start_position is not None else Point3D(0.0, 0.0, 0.0)
    moves: list[Move] = []

    for layer_idx, layer in enumerate(layers):
        for poly_idx, poly in enumerate(layer.polygons):
            if not poly.points:
                continue
            start_pt = _transform_vertex(poly.points[0], layer.z, kinematic_chain, transform_joints)
            # Travel to the start of this polygon.
            if current != start_pt:
                moves.append(
                    Move(
                        start=current,
                        end=start_pt,
                        syringe_id=syringe_id,
                        is_travel=True,
                        extrusion_volume_uL=0.0,
                        feed_mm_per_min=travel_feed,
                        segment_id=_segment_id(layer_idx, poly_idx, 0, "T"),
                        joints=joints,
                    )
                )
                current = start_pt
            # Extrude around the polygon, returning to its start.
            pts = [*poly.points, poly.points[0]]
            for edge_idx in range(len(pts) - 1):
                b = pts[edge_idx + 1]
                end_pt = _transform_vertex(b, layer.z, kinematic_chain, transform_joints)
                if end_pt == current:
                    continue
                length = current.distance_to(end_pt)
                moves.append(
                    Move(
                        start=current,
                        end=end_pt,
                        syringe_id=syringe_id,
                        is_travel=False,
                        extrusion_volume_uL=length * volume_per_mm_uL,
                        feed_mm_per_min=extrude_feed,
                        segment_id=_segment_id(layer_idx, poly_idx, edge_idx + 1, "E"),
                        joints=joints,
                    )
                )
                current = end_pt

    return moves


__all__ = ["generate_perimeter_paths"]
