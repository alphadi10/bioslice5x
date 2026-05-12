"""Conformal perimeter path generation — Phase 2c.

Walks each `ConformalLayer`'s vertices, applies the kinematic transform to
move from part frame to machine frame, and emits `Move`s with per-vertex
joints attached. Same Move type as flat slicing — the postprocessor doesn't
need to know which slicer produced the path.

Bath travel-speed reduction: queried per-travel-Z from the recipe's bath
spec. If no bath is specified, falls back to the legacy
`slicing.travel_speed_reduction_in_bath` uniform multiplier.

Before path materialization, the global joint sequence is run through
`smooth_through_singularity` so contiguous runs of in-band tilt do not
emit swivel jitter through the singular pose. The smoothing threshold is
recipe-controlled (`slicing.singularity_threshold_deg`).
"""

from __future__ import annotations

import math

from bioslice5x.bath.models import BathSpec
from bioslice5x.geometry.conformal_slicer import ConformalLayer, ConformalVertex
from bioslice5x.kinematics.canonical import JointAngles
from bioslice5x.kinematics.chain import KinematicChain
from bioslice5x.kinematics.singularity import smooth_through_singularity
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


def _smooth_layer_joints(
    layers: list[ConformalLayer],
    *,
    threshold_rad: float,
) -> list[list[JointAngles]]:
    """Smooth swivel through singular spans across the full print's joint
    sequence, then split back into per-layer lists.

    Smoothing applies when tilt occasionally crosses the singular band
    inside a path that otherwise spans real tilt motion — the wrap-tilt-
    axis (x or y) case. For a wrap-around-Z print, tilt is identically
    zero by construction (the canonical formula is `swivel = -θ`,
    `tilt = 0`) and the swivel sweep IS the deposition path, not a free
    tool-orientation choice. Collapsing swivel through the "singular
    band" there would erase the print. Detect that case by checking
    whether any joint sits *outside* the band, and skip smoothing if
    none do.

    The smoothing is otherwise done on the concatenated joint sequence
    (not per-layer) so a singular span that straddles two layers — common
    when the layer transition lies inside the singular band — is
    interpolated as one span rather than two abrupt ones.
    """
    flat: list[JointAngles] = []
    spans: list[int] = []  # vertex count per layer
    for layer in layers:
        spans.append(len(layer.vertices))
        flat.extend(v.joints for v in layer.vertices)
    has_out_of_band = any(abs(j.tilt_rad) >= threshold_rad for j in flat)
    if not has_out_of_band:
        # Every joint sits inside the singular band — almost certainly a
        # wrap-around-swivel-axis print where swivel encodes the path.
        # Smoothing here would interpolate the path to nothing.
        cursor = 0
        out: list[list[JointAngles]] = []
        for n in spans:
            out.append(flat[cursor : cursor + n])
            cursor += n
        return out
    smoothed = smooth_through_singularity(
        flat,
        threshold_rad=threshold_rad,
        warn=False,
    )
    out = []
    cursor = 0
    for n in spans:
        out.append(smoothed[cursor : cursor + n])
        cursor += n
    return out


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

    # Apply singularity smoothing on the global joint sequence before
    # materializing the path. The smoothed joints replace each vertex's
    # tilt/swivel via a fresh ConformalVertex with the original part_xyz
    # so downstream code stays unchanged.
    smoothed_per_layer = _smooth_layer_joints(
        layers,
        threshold_rad=math.radians(slicing.singularity_threshold_deg),
    )
    layers_smoothed: list[ConformalLayer] = []
    for layer, smoothed_joints in zip(layers, smoothed_per_layer, strict=True):
        smoothed_vertices = tuple(
            ConformalVertex(part_xyz=v.part_xyz, joints=j)
            for v, j in zip(layer.vertices, smoothed_joints, strict=True)
        )
        layers_smoothed.append(
            ConformalLayer(
                layer_index=layer.layer_index,
                s_along_axis_mm=layer.s_along_axis_mm,
                vertices=smoothed_vertices,
                is_closed=layer.is_closed,
                is_sub_arc_start=layer.is_sub_arc_start,
                sub_arc_index=layer.sub_arc_index,
            )
        )

    current = start_position if start_position is not None else Point3D(0.0, 0.0, 0.0)
    moves: list[Move] = []

    for layer in layers_smoothed:
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
            travel_segment_id = (
                f"L{layer.layer_index:04d}_SUBARC{layer.sub_arc_index:02d}_T"
                if layer.is_sub_arc_start
                else f"L{layer.layer_index:04d}_T"
            )
            moves.append(
                Move(
                    start=current,
                    end=first,
                    syringe_id=syringe_id,
                    is_travel=True,
                    extrusion_volume_uL=0.0,
                    feed_mm_per_min=_bath_aware_travel_feed(first, slicing, bath),
                    segment_id=travel_segment_id,
                    joints=layer.vertices[0].joints,
                    is_sub_arc_start=layer.is_sub_arc_start,
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
