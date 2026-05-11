"""Conformal perimeter path generation — Phase 2c.

Walks each `ConformalLayer`'s vertices, applies the kinematic transform to
move from part frame to machine frame, and emits `Move`s with per-vertex
joints attached. Same Move type as flat slicing — the postprocessor doesn't
need to know which slicer produced the path.

Bath travel-speed reduction: queried per-travel-Z from the recipe's bath
spec. If no bath is specified, falls back to the legacy
`slicing.travel_speed_reduction_in_bath` uniform multiplier.
"""

from __future__ import annotations

from bioslice5x.bath.models import BathSpec
from bioslice5x.geometry.conformal_slicer import ConformalLayer
from bioslice5x.kinematics.chain import KinematicChain
from bioslice5x.pathing.types import Move, Point3D
from bioslice5x.recipe.models import SlicingParams


def _bath_aware_travel_feed(
    point: Point3D,
    slicing: SlicingParams,
    bath: BathSpec | None,
) -> float:
    """Travel feedrate at a given machine-frame point.

    With a bath spec, the bath model determines the multiplier at that
    point (future bath kinds may depend on XY as well as Z). Without one,
    use the legacy uniform multiplier from SlicingParams.
    """
    base = slicing.travel_speed_mm_per_min
    if bath is None:
        return base * slicing.travel_speed_reduction_in_bath
    return base * bath.travel_speed_multiplier(point)


def generate_conformal_perimeter_paths(
    layers: list[ConformalLayer],
    syringe_id: int,
    slicing: SlicingParams,
    *,
    kinematic_chain: KinematicChain,
    bath: BathSpec | None = None,
    start_position: Point3D | None = None,
) -> list[Move]:
    """Walk conformal layers into a flat list of Moves with attached joints."""
    volume_per_mm_uL = slicing.line_width_mm * slicing.layer_height_mm
    extrude_feed = slicing.print_speed_mm_per_min

    current = start_position if start_position is not None else Point3D(0.0, 0.0, 0.0)
    moves: list[Move] = []

    for layer in layers:
        if not layer.vertices:
            continue
        # Transform every vertex's part-frame point through the kinematic
        # chain using that vertex's joints. The vertex's joints are also
        # attached to the resulting Move for the postprocessor.
        machine_pts: list[Point3D] = []
        for v in layer.vertices:
            mx, my, mz = kinematic_chain.part_to_machine(v.part_xyz, v.joints)
            machine_pts.append(Point3D(mx, my, mz))
        # Closing edge: if the layer is closed, append the first machine
        # point at the end so the perimeter returns to its start.
        if layer.is_closed:
            machine_pts.append(machine_pts[0])

        # Travel to the start of this layer.
        first = machine_pts[0]
        if current != first:
            moves.append(
                Move(
                    start=current,
                    end=first,
                    syringe_id=syringe_id,
                    is_travel=True,
                    extrusion_volume_uL=0.0,
                    feed_mm_per_min=_bath_aware_travel_feed(first, slicing, bath),
                    segment_id=f"L{layer.layer_index:04d}_T",
                    joints=layer.vertices[0].joints,
                )
            )
            current = first

        # Extrude along each edge.
        for edge_idx in range(len(machine_pts) - 1):
            end_pt = machine_pts[edge_idx + 1]
            if end_pt == current:
                continue
            length = current.distance_to(end_pt)
            # The joints at this edge belong to the *destination* vertex —
            # mirrors how G1 commands the target pose.
            dest_vertex_idx = (edge_idx + 1) % len(layer.vertices)
            joints = layer.vertices[dest_vertex_idx].joints
            moves.append(
                Move(
                    start=current,
                    end=end_pt,
                    syringe_id=syringe_id,
                    is_travel=False,
                    extrusion_volume_uL=length * volume_per_mm_uL,
                    feed_mm_per_min=extrude_feed,
                    segment_id=f"L{layer.layer_index:04d}_E{edge_idx:04d}",
                    joints=joints,
                )
            )
            current = end_pt

    return moves


__all__ = ["generate_conformal_perimeter_paths"]
