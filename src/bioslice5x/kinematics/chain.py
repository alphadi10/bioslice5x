"""KinematicChain Protocol and concrete implementations.

Path generation calls only the Protocol; it never special-cases on the
concrete implementation. v1 ships `ThreeAxisKinematics` and
`TiltSwivelKinematics`; A+B and other configurations plug in as siblings.
"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from bioslice5x.kinematics.canonical import (
    AxisName,
    JointAngles,
    machine_to_part_xyz,
    part_to_machine_xyz,
)
from bioslice5x.profile.models import MachineProfile

ChainKind = Literal["three_axis", "tilt_swivel"]


@runtime_checkable
class KinematicChain(Protocol):
    """Forward/inverse kinematic interface.

    Implementations transform between part-frame (mesh-authored) and
    machine-frame (toolhead-reachable) Cartesian coordinates given the
    current canonical joint angles.
    """

    kind: ChainKind

    def part_to_machine(
        self, part_xyz: tuple[float, float, float], joints: JointAngles
    ) -> tuple[float, float, float]: ...

    def machine_to_part(
        self, machine_xyz: tuple[float, float, float], joints: JointAngles
    ) -> tuple[float, float, float]: ...


class ThreeAxisKinematics:
    """No-op kinematic chain. Joints are ignored; part = machine.

    Phase 2a uses this exclusively. The Slicer instantiates it from any
    profile with `kinematic_chain.kind == "three_axis"`. Keeps the
    pipeline's transform call site uniform across phases.
    """

    kind: ChainKind = "three_axis"

    def part_to_machine(
        self, part_xyz: tuple[float, float, float], joints: JointAngles
    ) -> tuple[float, float, float]:
        return part_xyz

    def machine_to_part(
        self, machine_xyz: tuple[float, float, float], joints: JointAngles
    ) -> tuple[float, float, float]:
        return machine_xyz


class TiltSwivelKinematics:
    """Two-rotary-on-the-bed chain.

    Wraps the canonical math with the axes-of-rotation read from the
    machine profile. `tilt_about` and `swivel_about` are the *world* axes
    each joint rotates about — typically `"x"` and `"z"` for Open5X-style
    Prusa, or `"y"` and `"z"` for Voron/Jubilee-style builds. The G-code
    letter that each joint emits as is *not* this module's concern — the
    postprocessor handles that.
    """

    kind: ChainKind = "tilt_swivel"

    def __init__(self, *, tilt_about: AxisName, swivel_about: AxisName) -> None:
        if tilt_about == swivel_about:
            raise ValueError(f"tilt and swivel cannot rotate about the same axis ({tilt_about!r})")
        self.tilt_about = tilt_about
        self.swivel_about = swivel_about

    def part_to_machine(
        self, part_xyz: tuple[float, float, float], joints: JointAngles
    ) -> tuple[float, float, float]:
        return part_to_machine_xyz(
            part_xyz, joints, tilt_about=self.tilt_about, swivel_about=self.swivel_about
        )

    def machine_to_part(
        self, machine_xyz: tuple[float, float, float], joints: JointAngles
    ) -> tuple[float, float, float]:
        return machine_to_part_xyz(
            machine_xyz, joints, tilt_about=self.tilt_about, swivel_about=self.swivel_about
        )


def kinematic_chain_from_profile(profile: MachineProfile) -> KinematicChain:
    """Construct the right kinematic implementation for a given profile."""
    spec = profile.kinematic_chain
    if spec.kind == "three_axis":
        return ThreeAxisKinematics()
    if spec.kind == "tilt_swivel":
        assert spec.tilt is not None
        assert spec.swivel is not None
        return TiltSwivelKinematics(
            tilt_about=spec.tilt.rotates_about,
            swivel_about=spec.swivel.rotates_about,
        )
    raise ValueError(f"unsupported kinematic_chain kind: {spec.kind!r}")


__all__ = [
    "ChainKind",
    "KinematicChain",
    "ThreeAxisKinematics",
    "TiltSwivelKinematics",
    "kinematic_chain_from_profile",
]
