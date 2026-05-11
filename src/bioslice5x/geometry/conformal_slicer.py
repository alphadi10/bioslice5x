"""Conformal slicer — wrap-around-axis mode (Phase 2c / 2c.2).

Scope: wrap-around-axis only. Fully-arbitrary curved layers
(surface-normal-following with arbitrary base geometry) is a CGAL-class
geometry problem deferred to a later phase.

Three wrap-axis cases:

- `wrap_axis="z"`: cylinder axis along world Z (Open5X swivel). Swivel
  sweeps through θ. Full revolutions trivially permitted because swivel
  range is effectively unbounded on both shipped profiles.
- `wrap_axis="x"`: cylinder axis along world X (Open5X Prusa tilt). Tilt
  sweeps through θ. Tilt range is finite (~±200° on Prusa); per ADR-001,
  arcs exceeding range require explicit `allow_tilt_arc_split` opt-in.
- `wrap_axis="y"`: cylinder axis along world Y (Voron tilt). Same as `"x"`
  but the tilt joint rotates about Y. Voron tilt range is ~±110°, so
  even a 270° wrap requires arc-split.

The slicer produces `ConformalLayer`s carrying part-frame vertices and
their canonical (tilt, swivel) joints. The Slicer applies the kinematic
chain and the postprocessor renders the G-code letters. The two halves of
that split (geometry vs letter mapping) remain decoupled.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import trimesh

from bioslice5x.errors import ClampingExceededError
from bioslice5x.geometry.mesh import mesh_z_extent
from bioslice5x.kinematics.canonical import JointAngles
from bioslice5x.profile.models import MachineProfile
from bioslice5x.recipe.models import WrapAroundAxisSlicing


@dataclass(frozen=True)
class ConformalVertex:
    """A vertex on a conformal layer, in *part* frame, with attached joints."""

    part_xyz: tuple[float, float, float]
    joints: JointAngles


@dataclass(frozen=True)
class ConformalLayer:
    """One axial pass at constant `s` along the wrap axis.

    `is_sub_arc_start` marks the first layer of a sub-arc when arc-split
    is active — the path generator emits a retract-clear move before it.
    """

    layer_index: int
    s_along_axis_mm: float
    vertices: tuple[ConformalVertex, ...]
    is_closed: bool
    is_sub_arc_start: bool = False
    sub_arc_index: int = 0


def _axial_extent(mesh: trimesh.Trimesh, wrap_axis: Literal["x", "y", "z"]) -> tuple[float, float]:
    """Mesh's bounding-box extent along the wrap axis."""
    if wrap_axis == "z":
        return mesh_z_extent(mesh)
    bounds = mesh.bounds  # shape (2, 3)
    idx = {"x": 0, "y": 1, "z": 2}[wrap_axis]
    return float(bounds[0][idx]), float(bounds[1][idx])


def _part_frame_vertex_and_joints(
    wrap_axis: Literal["x", "y", "z"], s: float, theta: float, radius: float
) -> tuple[tuple[float, float, float], JointAngles]:
    """Cylinder-surface vertex in part frame and the joint angles that bring
    it under the vertical syringe.

    The conformal slicer is letter-free: it produces canonical (tilt, swivel)
    angles; the postprocessor maps them to G-code letters per profile.

    `wrap_axis="z"`: cylinder along world Z. Sweep θ around it.
        Part-frame point: (r·cos θ, r·sin θ, s).
        Bring under vertical syringe: swivel = -θ (tilt = 0).
    `wrap_axis="x"`: cylinder along world X. Sweep θ around it.
        Part-frame point: (s, r·cos θ, r·sin θ).
        Bring under vertical syringe: tilt = π/2 - θ (swivel = 0).
    `wrap_axis="y"`: cylinder along world Y. Sweep θ around it.
        Part-frame point: (r·sin θ, s, r·cos θ).
        Bring under vertical syringe: tilt = θ (swivel = 0); chosen so that
        θ = 0 corresponds to "top of cylinder" (z = r).
    """
    if wrap_axis == "z":
        part = (radius * math.cos(theta), radius * math.sin(theta), s)
        return part, JointAngles(tilt_rad=0.0, swivel_rad=-theta)
    if wrap_axis == "x":
        part = (s, radius * math.cos(theta), radius * math.sin(theta))
        return part, JointAngles(tilt_rad=math.pi / 2 - theta, swivel_rad=0.0)
    if wrap_axis == "y":
        part = (radius * math.sin(theta), s, radius * math.cos(theta))
        return part, JointAngles(tilt_rad=theta, swivel_rad=0.0)
    raise ValueError(f"unknown wrap_axis {wrap_axis!r}")


def _is_swivel_axis(profile: MachineProfile, wrap_axis: Literal["x", "y", "z"]) -> bool:
    """True if `wrap_axis` aligns with the profile's swivel rotation axis.

    Swivel has effectively unbounded range, so arc-clamping doesn't apply.
    """
    sw = profile.kinematic_chain.swivel
    return sw is not None and sw.rotates_about == wrap_axis


def _is_tilt_axis(profile: MachineProfile, wrap_axis: Literal["x", "y", "z"]) -> bool:
    """True if `wrap_axis` aligns with the profile's tilt rotation axis."""
    t = profile.kinematic_chain.tilt
    return t is not None and t.rotates_about == wrap_axis


def _tilt_range_deg(profile: MachineProfile) -> float:
    """Total available tilt range in degrees (max - min)."""
    t = profile.kinematic_chain.tilt
    if t is None:
        return 0.0
    lo, hi = t.range_deg
    return hi - lo


def _min_arc_split_count(arc_span_deg: float, tilt_range_deg: float) -> int:
    """ADR-001: minimum N such that |arc_span| / N <= tilt_range."""
    if tilt_range_deg <= 0:
        raise ValueError(f"non-positive tilt range: {tilt_range_deg}")
    return max(1, math.ceil(abs(arc_span_deg) / tilt_range_deg))


def wrap_around_axis_slice(
    mesh: trimesh.Trimesh,
    spec: WrapAroundAxisSlicing,
    *,
    layer_height_mm: float,
    line_width_mm: float,
    profile: MachineProfile,
) -> list[ConformalLayer]:
    """Slice a roughly-cylindrical mesh into conformal layers around `wrap_axis`.

    Implements ADR-001 for the tilt-axis cases: refuse loudly when the
    requested arc exceeds the profile's tilt range; permit arc-split with
    explicit opt-in. Swivel-axis wraps (z on both shipped profiles) skip
    the clamping check because swivel range is unbounded.
    """
    assert layer_height_mm > 0.0
    radius = spec.cylinder_radius_mm
    arc_start_rad = math.radians(spec.arc_start_deg)
    arc_end_rad = math.radians(spec.arc_end_deg)
    arc_span_deg = spec.arc_end_deg - spec.arc_start_deg
    arc_span_rad = arc_end_rad - arc_start_rad
    is_closed_360 = abs(abs(arc_span_rad) - 2 * math.pi) < 1e-9

    # ADR-001: clamping check for tilt-axis wraps.
    sub_arcs: list[tuple[float, float]]
    if _is_swivel_axis(profile, spec.wrap_axis):
        # Swivel sweeps; unbounded — single sub-arc covering the request.
        sub_arcs = [(arc_start_rad, arc_end_rad)]
    elif _is_tilt_axis(profile, spec.wrap_axis):
        tilt_range = _tilt_range_deg(profile)
        min_split = _min_arc_split_count(arc_span_deg, tilt_range)
        if min_split == 1:
            sub_arcs = [(arc_start_rad, arc_end_rad)]
        elif not spec.allow_tilt_arc_split or spec.arc_split_count < min_split:
            raise ClampingExceededError(
                requested_arc_deg=arc_span_deg,
                tilt_range_deg=tilt_range,
                minimum_sub_arcs=min_split,
                wrap_axis=spec.wrap_axis,
            )
        else:
            n = spec.arc_split_count
            step = arc_span_rad / n
            sub_arcs = [
                (arc_start_rad + i * step, arc_start_rad + (i + 1) * step) for i in range(n)
            ]
    else:
        raise ValueError(
            f"wrap_axis={spec.wrap_axis!r} does not match the profile's tilt "
            f"or swivel rotation axis"
        )

    # Axial sample positions along the wrap axis.
    ax_min, ax_max = _axial_extent(mesh, spec.wrap_axis)
    if ax_max <= ax_min:
        raise ValueError(f"empty wrap-axis extent [{ax_min}, {ax_max}]")
    first_s = ax_min + line_width_mm / 2.0
    n_axial = max(1, math.floor((ax_max - first_s) / line_width_mm) + 1)
    axial_positions = [first_s + i * line_width_mm for i in range(n_axial)]

    # Arc-sample spacing.
    arc_sampling_mm = spec.conformal_arc_sampling_mm or line_width_mm

    # Build layers across all sub-arcs.
    layers: list[ConformalLayer] = []
    layer_idx = 0
    for sub_arc_idx, (sub_start_rad, sub_end_rad) in enumerate(sub_arcs):
        sub_span_rad = sub_end_rad - sub_start_rad
        sub_arc_length_mm = abs(sub_span_rad) * radius
        n_theta = max(8, math.ceil(sub_arc_length_mm / arc_sampling_mm))
        # Whether *this sub-arc* closes back on itself (only the full-360,
        # single-sub-arc, swivel-axis case).
        sub_closed = is_closed_360 and len(sub_arcs) == 1
        dtheta = sub_span_rad / n_theta if sub_closed else sub_span_rad / (n_theta - 1)
        for axial_i, s in enumerate(axial_positions):
            verts: list[ConformalVertex] = []
            for j in range(n_theta):
                theta = sub_start_rad + j * dtheta
                part_xyz, joints = _part_frame_vertex_and_joints(spec.wrap_axis, s, theta, radius)
                verts.append(ConformalVertex(part_xyz=part_xyz, joints=joints))
            layers.append(
                ConformalLayer(
                    layer_index=layer_idx,
                    s_along_axis_mm=s,
                    vertices=tuple(verts),
                    is_closed=sub_closed,
                    is_sub_arc_start=(axial_i == 0 and sub_arc_idx > 0),
                    sub_arc_index=sub_arc_idx,
                )
            )
            layer_idx += 1

    return layers


__all__ = [
    "ConformalLayer",
    "ConformalVertex",
    "wrap_around_axis_slice",
]
