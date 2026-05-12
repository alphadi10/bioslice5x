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

import math

from bioslice5x.bath.models import BathSpec
from bioslice5x.geometry.conformal_slicer import ConformalLayer
from bioslice5x.kinematics.chain import KinematicChain
from bioslice5x.pathing.types import Move, Point3D
from bioslice5x.recipe.models import SlicingParams


def _part_frame_distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    """Euclidean distance between two part-frame vertices.

    For wrap-around-axis prints this is the arc length the bed traces
    under the (stationary) needle when transitioning between vertices —
    i.e., the actual deposition length, which governs extrusion volume
    and time. Cartesian machine-frame distance collapses to ≈0 here
    because the toolhead does not translate; only the rotary joints
    change. See the call site in `generate_conformal_perimeter_paths`.
    """
    return math.sqrt(sum((ai - bi) ** 2 for ai, bi in zip(a, b, strict=True)))


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
        # chain using that vertex's joints. Both the machine-frame point
        # (for G-code X/Y/Z tokens) and the part-frame point (for the
        # arc-length extrusion calc) are kept — they diverge whenever
        # the rotary joints are non-zero, which is the whole point of
        # 5-axis conformal slicing.
        machine_pts: list[Point3D] = []
        part_pts: list[tuple[float, float, float]] = []
        for v in layer.vertices:
            mx, my, mz = kinematic_chain.part_to_machine(v.part_xyz, v.joints)
            machine_pts.append(Point3D(mx, my, mz))
            part_pts.append(v.part_xyz)
        # Closing edge: if the layer is closed, append the first point
        # at the end so the perimeter returns to its start.
        if layer.is_closed:
            machine_pts.append(machine_pts[0])
            part_pts.append(part_pts[0])

        # Travel to the start of this layer. Travel feed is set on the
        # cartesian distance because the toolhead actually *does*
        # translate between layers (Z + tool-clear move); part-frame
        # distance isn't the right scalar for travel timing.
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
        current_part = part_pts[0]

        # Extrude along each edge. The extrusion length is the part-frame
        # arc length between consecutive vertices — what the deposition
        # substrate actually traces. See ARCHITECTURE.md §3.
        for edge_idx in range(len(machine_pts) - 1):
            end_pt = machine_pts[edge_idx + 1]
            end_part = part_pts[edge_idx + 1]
            part_length = _part_frame_distance(current_part, end_part)
            if part_length <= 0.0:
                current = end_pt
                current_part = end_part
                continue
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
                    extrusion_volume_uL=part_length * volume_per_mm_uL,
                    feed_mm_per_min=extrude_feed,
                    segment_id=f"L{layer.layer_index:04d}_E{edge_idx:04d}",
                    joints=joints,
                    # Anchor flow_rate and timing to the part-frame arc
                    # length (the deposition length under the needle),
                    # not the machine-frame motion of the stationary
                    # toolhead — the load-bearing fix for the 5-axis
                    # E=0 bug.
                    effective_length_mm_override=part_length,
                )
            )
            current = end_pt
            current_part = end_part

    return moves


__all__ = ["generate_conformal_perimeter_paths"]
