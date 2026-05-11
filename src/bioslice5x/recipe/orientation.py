"""OrientationProvider factory — resolves a Recipe's print_orientation into
a per-layer joint-angles lookup.

Mirrors `kinematic_chain_from_profile` in `kinematics/chain.py`: the
factory dispatches on the orientation discriminator (`kind`) so adding a
new kind (e.g., `normal_following` in a later phase) does not require
Slicer changes. The Slicer only ever calls
`provider.joints_for_layer(layer_idx)`.
"""

from __future__ import annotations

import math
from typing import Protocol, runtime_checkable

from bioslice5x.kinematics.canonical import JointAngles
from bioslice5x.recipe.models import FixedOrientation, PerLayerOrientation, Recipe


@runtime_checkable
class OrientationProvider(Protocol):
    """Source of joint angles per layer index. Called by the Slicer between
    geometry slicing and path generation."""

    def joints_for_layer(self, layer_idx: int) -> JointAngles: ...


class _Fixed:
    """Always returns the same joints."""

    def __init__(self, tilt_deg: float, swivel_deg: float) -> None:
        self._joints = JointAngles(
            tilt_rad=math.radians(tilt_deg), swivel_rad=math.radians(swivel_deg)
        )

    def joints_for_layer(self, layer_idx: int) -> JointAngles:
        return self._joints


class _PerLayer:
    """Indexed lookup; raises IndexError on mismatch.

    Lengths of `tilts_deg` and `swivels_deg` must match; the Slicer is
    responsible for asserting that they also match the actual number of
    layers produced by the slicer.
    """

    def __init__(self, tilts_deg: list[float], swivels_deg: list[float]) -> None:
        if len(tilts_deg) != len(swivels_deg):
            raise ValueError(
                f"per_layer orientation: tilts_deg has {len(tilts_deg)} entries but "
                f"swivels_deg has {len(swivels_deg)}; must match."
            )
        self._joints = [
            JointAngles(tilt_rad=math.radians(t), swivel_rad=math.radians(s))
            for t, s in zip(tilts_deg, swivels_deg, strict=True)
        ]

    @property
    def layer_count(self) -> int:
        return len(self._joints)

    def joints_for_layer(self, layer_idx: int) -> JointAngles:
        if not (0 <= layer_idx < len(self._joints)):
            raise IndexError(
                f"per_layer orientation: layer_idx {layer_idx} out of range "
                f"[0, {len(self._joints)})"
            )
        return self._joints[layer_idx]


def orientation_provider_from_recipe(recipe: Recipe) -> OrientationProvider:
    """Factory: turn a Recipe.print_orientation into a callable provider."""
    spec = recipe.print_orientation
    if isinstance(spec, FixedOrientation):
        return _Fixed(spec.tilt_deg, spec.swivel_deg)
    if isinstance(spec, PerLayerOrientation):
        return _PerLayer(spec.tilts_deg, spec.swivels_deg)
    raise ValueError(f"unsupported print_orientation kind: {type(spec).__name__}")


__all__ = ["OrientationProvider", "orientation_provider_from_recipe"]
