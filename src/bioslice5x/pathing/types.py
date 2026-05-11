"""Toolpath data types.

A toolpath is a sequence of `Move`s. Each move is a straight-line segment
from `start` to `end`, either an extrusion or a travel. The `syringe_id`
identifies which syringe owns the move — relevant for multi-syringe (Phase
2d) tool changes; in 2a all moves carry the single syringe's id.

Move coordinates are always in **machine frame** (the toolhead-reachable
Cartesian frame). For 5-axis chains, the slicer applies the part-frame →
machine-frame kinematic transform before constructing the Move, and the
`joints` field carries the canonical (tilt, swivel) angles that the
postprocessor renders as G-code letters.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from bioslice5x.kinematics.canonical import JointAngles


@dataclass(frozen=True)
class Point3D:
    """A point in machine 3-space."""

    x: float
    y: float
    z: float

    def distance_to(self, other: Point3D) -> float:
        return math.sqrt(
            (self.x - other.x) ** 2 + (self.y - other.y) ** 2 + (self.z - other.z) ** 2
        )


@dataclass(frozen=True)
class Move:
    """A single G1 segment, with extrusion or travel semantics.

    `joints` is `None` on 3-axis profiles; on tilt_swivel profiles it is the
    canonical joint configuration the postprocessor emits as A/C (or B/C)
    tokens. The Cartesian (`start`, `end`) coordinates are already in the
    machine frame — the kinematic transform happens upstream in the slicer.
    """

    start: Point3D
    end: Point3D
    syringe_id: int
    is_travel: bool
    extrusion_volume_uL: float
    feed_mm_per_min: float
    segment_id: str  # stable identifier for error reporting
    joints: JointAngles | None = None

    @property
    def length_mm(self) -> float:
        return self.start.distance_to(self.end)

    @property
    def flow_rate_uL_per_s(self) -> float:
        """Volume per second, from extrusion volume and traversal time."""
        if self.is_travel or self.extrusion_volume_uL <= 0 or self.feed_mm_per_min <= 0:
            return 0.0
        length = self.length_mm
        if length <= 0:
            return 0.0
        seconds = (length / self.feed_mm_per_min) * 60.0
        return self.extrusion_volume_uL / seconds


__all__ = ["Move", "Point3D"]
