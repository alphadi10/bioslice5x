"""Machine profile pydantic models.

The kinematics module works in canonical (tilt, swivel) angles; this profile
holds the mapping to G-code letters. A Voron-style B+C operator changes
`letter: A` → `letter: B` here, with no kinematics code touched.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BuildVolume(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    x_mm: tuple[float, float]
    y_mm: tuple[float, float]
    z_mm: tuple[float, float]

    @model_validator(mode="after")
    def _check_ordering(self) -> BuildVolume:
        for axis, (lo, hi) in (("x", self.x_mm), ("y", self.y_mm), ("z", self.z_mm)):
            if lo > hi:
                raise ValueError(f"{axis} build-volume low ({lo}) must be <= high ({hi})")
        return self


class TiltSwivelAxis(BaseModel):
    """Mapping from a canonical (tilt or swivel) joint to a G-code letter."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    rotates_about: Literal["x", "y", "z"]
    letter: str = Field(min_length=1, max_length=1)
    invert: bool = False
    range_deg: tuple[float, float]
    max_feed_deg_per_min: float = Field(default=5000.0, gt=0.0)

    @model_validator(mode="after")
    def _check_range(self) -> TiltSwivelAxis:
        lo, hi = self.range_deg
        if lo >= hi:
            raise ValueError(f"range_deg low ({lo}) must be < high ({hi})")
        return self


class KinematicChain(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["three_axis", "tilt_swivel"]
    tilt: TiltSwivelAxis | None = None
    swivel: TiltSwivelAxis | None = None

    @model_validator(mode="after")
    def _check_kind_consistency(self) -> KinematicChain:
        if self.kind == "three_axis" and (self.tilt is not None or self.swivel is not None):
            raise ValueError("three_axis kinematic_chain must not declare tilt/swivel axes")
        if self.kind == "tilt_swivel" and (self.tilt is None or self.swivel is None):
            raise ValueError("tilt_swivel kinematic_chain requires both tilt and swivel axes")
        return self


class MachineProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    firmware: Literal["rrf", "marlin"] = "rrf"
    build_volume: BuildVolume
    kinematic_chain: KinematicChain
    max_xy_feed_mm_per_min: float = Field(default=12000.0, gt=0.0)
    max_z_feed_mm_per_min: float = Field(default=750.0, gt=0.0)
    max_e_feed_uL_per_min: float = Field(default=100.0, gt=0.0)
    has_heated_bed: bool = False
    notes: str = ""


__all__ = ["BuildVolume", "KinematicChain", "MachineProfile", "TiltSwivelAxis"]
