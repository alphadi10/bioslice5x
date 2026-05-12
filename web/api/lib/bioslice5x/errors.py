"""Domain-specific exceptions for BioSlice5X.

Defined at the package boundary so callers can `except bioslice5x.errors.X`
without importing internal modules. Exceptions are designed to carry enough
structured context that a CLI or notebook can present an actionable message.
"""

from __future__ import annotations

from dataclasses import dataclass


class BioSlice5XError(Exception):
    """Base for all package-specific errors."""


@dataclass
class CellViabilityError(BioSlice5XError):
    """Raised when a planned path would exceed a bioink's cell-safety shear limit.

    The G-code emitter must not run when this is raised (unless the caller has
    explicitly passed `--force`, which produces a tagged-override output file).
    """

    segment_id: str
    computed_wall_shear_pa: float
    threshold_pa: float
    bioink_name: str
    cell_type: str
    remediation: str = ""

    def __str__(self) -> str:
        base = (
            f"segment {self.segment_id}: computed wall shear "
            f"{self.computed_wall_shear_pa:.1f} Pa exceeds "
            f"{self.bioink_name}/{self.cell_type} limit "
            f"{self.threshold_pa:.1f} Pa"
        )
        if self.remediation:
            return f"{base} ({self.remediation})"
        return base


@dataclass
class KinematicSingularityError(BioSlice5XError):
    """Raised when a path passes through a singular kinematic configuration that
    cannot be resolved by the active replanner."""

    segment_id: str
    joint_angles_deg: tuple[float, ...]
    kind: str

    def __str__(self) -> str:
        return (
            f"segment {self.segment_id}: {self.kind} singularity at angles {self.joint_angles_deg}"
        )


@dataclass
class BathCollisionError(BioSlice5XError):
    """Raised when the needle path would intersect already-deposited geometry
    in a way the path planner cannot route around."""

    segment_id: str
    detail: str

    def __str__(self) -> str:
        return f"segment {self.segment_id}: bath collision — {self.detail}"


@dataclass
class ProfileValidationError(BioSlice5XError):
    """Raised when a machine profile or recipe fails schema/range validation."""

    source: str
    detail: str

    def __str__(self) -> str:
        return f"{self.source}: {self.detail}"


@dataclass
class ClampingExceededError(BioSlice5XError):
    """Raised when a wrap-around-tilt-axis arc exceeds the profile's tilt range.

    Per ADR-001 (`docs/adr/0001-wrap-tilt-clamping.md`): the default is
    refuse-loudly. The caller can opt into arc-split via the recipe's
    `slicing.mode.allow_tilt_arc_split: true` flag, in which case the slicer
    splits the wrap into `n_sub_arcs` sub-arcs separated by retract-clear
    moves. Setting the flag below the required minimum still raises this
    error — partial wraps are a worse failure mode than a clear refusal.
    """

    requested_arc_deg: float
    tilt_range_deg: float
    minimum_sub_arcs: int
    wrap_axis: str

    def __str__(self) -> str:
        return (
            f"requested arc {self.requested_arc_deg:.1f}° on wrap_axis={self.wrap_axis!r} "
            f"exceeds profile tilt range {self.tilt_range_deg:.1f}°; "
            f"minimum sub-arc count is {self.minimum_sub_arcs}. "
            f"Set slicing.mode.allow_tilt_arc_split=true and "
            f"slicing.mode.arc_split_count={self.minimum_sub_arcs} (or higher) to proceed."
        )


__all__ = [
    "BathCollisionError",
    "BioSlice5XError",
    "CellViabilityError",
    "ClampingExceededError",
    "KinematicSingularityError",
    "ProfileValidationError",
]
