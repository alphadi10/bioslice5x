"""Canonical kinematic math, KinematicChain dispatch, singularity handling.

The kinematics module is letter-free: it works in `(tilt_rad, swivel_rad)`.
G-code letter mapping happens at the postprocessor boundary, driven by the
machine profile. See ARCHITECTURE.md §8.1.
"""

from __future__ import annotations

from bioslice5x.kinematics.canonical import (
    AxisName,
    JointAngles,
    machine_to_part_xyz,
    part_to_machine_xyz,
    rotation_matrix,
)
from bioslice5x.kinematics.chain import (
    ChainKind,
    KinematicChain,
    ThreeAxisKinematics,
    TiltSwivelKinematics,
    kinematic_chain_from_profile,
)
from bioslice5x.kinematics.singularity import (
    DEFAULT_SINGULARITY_THRESHOLD_DEG,
    SingularitySpan,
    find_singularity_spans,
    is_in_singular_band,
    smooth_through_singularity,
)

__all__ = [
    "DEFAULT_SINGULARITY_THRESHOLD_DEG",
    "AxisName",
    "ChainKind",
    "JointAngles",
    "KinematicChain",
    "SingularitySpan",
    "ThreeAxisKinematics",
    "TiltSwivelKinematics",
    "find_singularity_spans",
    "is_in_singular_band",
    "kinematic_chain_from_profile",
    "machine_to_part_xyz",
    "part_to_machine_xyz",
    "rotation_matrix",
    "smooth_through_singularity",
]
