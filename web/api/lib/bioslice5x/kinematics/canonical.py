"""Canonical kinematic math — no G-code letters, no profile assumptions.

The kinematics module operates in canonical generalized coordinates
`(tilt_rad, swivel_rad)`. The mapping to G-code letters (`A`/`C`, `B`/`C`,
`U`/`V`, …) is the postprocessor's responsibility, read from the machine
profile at emit time. See ARCHITECTURE.md §8.1.

Convention:

- **Both rotaries are on the bed.** The toolhead stays vertical above the
  workspace ("tilt the bed, not the nozzle"); the part rotates with the bed.
- The part-frame point `(x_p, y_p, z_p)` is the location of a deposition
  vertex *as authored in the mesh*. The forward transform produces the
  machine-frame point `(x_m, y_m, z_m)` the toolhead must reach so the
  syringe needle touches that vertex.
- Two rotations are applied in fixed order: **swivel first, then tilt.** The
  plate sits in the tilt yoke, so when tilt is non-zero, the swivel axis
  itself tilts.

Forward:  `world = R_tilt(a) · R_swivel(c) · part`
Inverse:  `part  = R_swivel(-c) · R_tilt(-a) · world`

Rotation axes are configurable per machine profile (Open5X Prusa uses tilt
about world X; Voron-style builds tilt about world Y). The `axis` arguments
below are lowercase letters `"x"`, `"y"`, or `"z"` to match the YAML schema
field `rotates_about`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np
import numpy.typing as npt

AxisName = Literal["x", "y", "z"]


@dataclass(frozen=True)
class JointAngles:
    """Generalized coordinates of the two-DOF bed.

    `tilt_rad` is the tilt-yoke angle (Open5X letter A, Voron letter B, …).
    `swivel_rad` is the plate-rotation angle (Open5X / Voron letter C).
    Both are in radians and follow the right-hand rule about their world-axis
    of rotation (`rotates_about` in the machine profile).
    """

    tilt_rad: float
    swivel_rad: float


def rotation_matrix(axis: AxisName, angle_rad: float) -> npt.NDArray[np.float64]:
    """Return a 3x3 right-hand-rule rotation matrix about a world axis."""
    c = math.cos(angle_rad)
    s = math.sin(angle_rad)
    if axis == "x":
        return np.array([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]])
    if axis == "y":
        return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])
    if axis == "z":
        return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])
    raise ValueError(f"unknown axis {axis!r}, expected one of 'x', 'y', 'z'")


def part_to_machine_xyz(
    part_xyz: tuple[float, float, float],
    joints: JointAngles,
    *,
    tilt_about: AxisName,
    swivel_about: AxisName,
) -> tuple[float, float, float]:
    """Forward transform: part-frame vertex → machine-frame toolhead position.

    Applies `R_tilt(a) · R_swivel(c) · p_part`. Inverse is `machine_to_part_xyz`.
    """
    p = np.array(part_xyz, dtype=np.float64)
    r_swivel = rotation_matrix(swivel_about, joints.swivel_rad)
    r_tilt = rotation_matrix(tilt_about, joints.tilt_rad)
    out = r_tilt @ r_swivel @ p
    return float(out[0]), float(out[1]), float(out[2])


def machine_to_part_xyz(
    machine_xyz: tuple[float, float, float],
    joints: JointAngles,
    *,
    tilt_about: AxisName,
    swivel_about: AxisName,
) -> tuple[float, float, float]:
    """Inverse transform: machine-frame toolhead position → part-frame vertex.

    Applies `R_swivel(-c) · R_tilt(-a) · p_machine`.
    """
    p = np.array(machine_xyz, dtype=np.float64)
    r_tilt_inv = rotation_matrix(tilt_about, -joints.tilt_rad)
    r_swivel_inv = rotation_matrix(swivel_about, -joints.swivel_rad)
    out = r_swivel_inv @ r_tilt_inv @ p
    return float(out[0]), float(out[1]), float(out[2])


__all__ = [
    "AxisName",
    "JointAngles",
    "machine_to_part_xyz",
    "part_to_machine_xyz",
    "rotation_matrix",
]
