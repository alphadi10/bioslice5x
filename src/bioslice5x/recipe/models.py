"""Recipe pydantic models.

The recipe groups: syringes (with regions), slicing parameters (flat or
conformal mode), print orientation (fixed or per-layer), and an optional
bath spec. Every dispatch is by discriminated-union `kind` so adding new
variants (regions, slicing modes, orientation kinds, bath kinds) does not
break the call sites.


Single-bioink-whole-mesh is N=1 of the general multi-region form: a Region
with `kind="all"`. Future kinds (`bbox`, `submesh`) plug in here without
changing call sites. The slicer dispatches on `region.kind` once, in the
per-layer geometry partitioner.

`print_orientation` follows the same general-form principle: 2b ships
`kind: "fixed"` (single tilt/swivel applied to the whole print). Per-layer
or per-segment orientation is the general form that 2c+ will exercise; the
fixed case is N=1 of that.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bioslice5x.bath.models import BathSpec


class Needle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    inner_diameter_mm: float = Field(gt=0.0)
    length_mm: float = Field(gt=0.0)
    gauge_label: str = ""  # e.g., "25G" — informational


class RegionAll(BaseModel):
    """Whole-mesh region — the syringe owns every triangle.

    This is the v1 default and the N=1 case of the general multi-region
    form (ARCHITECTURE.md §8.5).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["all"] = "all"


class RegionBBox(BaseModel):
    """Axis-aligned bounding-box region in part frame, mm.

    The syringe owns every layer polygon clipped against this box.
    Layers whose z falls outside [min.z, max.z] are dropped entirely;
    remaining layers' polygons are intersected with the XY rectangle.

    Use case: the CHIPS pancreatic reference geometry — fibrin/MIN6 core
    inside a cylindrical bbox at the centre of the construct, collagen
    shell covering the full envelope but with a hole carved out by the
    core. (For "outer ring" syringe behaviour, set the shell syringe to
    `kind: all` — the bath self-heals through the inner band, and the
    overlap is fine because shear is bounded per-syringe.)

    Bounds are inclusive on both ends. Half-open or open-on-one-side
    forms can be expressed with very large / negative sentinel values.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["bbox"] = "bbox"
    min: tuple[float, float, float]
    max: tuple[float, float, float]

    @model_validator(mode="after")
    def _check_min_lt_max(self) -> RegionBBox:
        for axis, (lo, hi) in enumerate(zip(self.min, self.max, strict=True)):
            if lo > hi:
                axis_name = "xyz"[axis]
                raise ValueError(f"bbox min.{axis_name} ({lo}) must be <= max.{axis_name} ({hi})")
        return self


# Discriminated union — pydantic picks the right model from the `kind`
# tag. Future kinds (`submesh`, `volume_fraction`) become siblings here
# without touching the slicer's region-dispatch code path.
Region = RegionAll | RegionBBox


class Syringe(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: int = Field(ge=0)
    bioink: str  # name; resolved against the bioink library at slice time
    cell_payload: str  # name; resolved against the cell library
    needle: Needle
    region: Region = Field(default_factory=RegionAll)
    purge_volume_uL: float = Field(default=5.0, ge=0.0)
    # Syringe physical properties; defaults match a 1 mL BD slip-tip syringe.
    barrel_inner_diameter_mm: float = Field(default=4.65, gt=0.0)
    total_volume_uL: float = Field(default=1000.0, gt=0.0)
    # If None, the slicer uses the midpoint of the bioink's working temperature.
    temperature_setpoint_c: float | None = None


class FixedOrientation(BaseModel):
    """Same tilt + swivel applied to every layer of the print."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["fixed"] = "fixed"
    tilt_deg: float = 0.0
    swivel_deg: float = 0.0


class PerLayerOrientation(BaseModel):
    """Per-layer joint angles. Length must match the number of layers the
    slicer produces, or the slicer raises a clear validation error."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["per_layer"] = "per_layer"
    tilts_deg: list[float] = Field(default_factory=list)
    swivels_deg: list[float] = Field(default_factory=list)


# Discriminated union — pydantic v2 picks the right model from `kind`. A
# typo like `kind: "perlayer"` fails validation at recipe load with a clear
# "Input tag 'perlayer' does not match any of the expected tags" message.
PrintOrientation = FixedOrientation | PerLayerOrientation


class FlatSlicing(BaseModel):
    """Flat horizontal slicing — Phase 2a/2b default."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["flat"] = "flat"


class WrapAroundAxisSlicing(BaseModel):
    """Conformal slicing: cylindrical shells around a chosen wrap axis.

    `wrap_axis` selects which world axis the cylinder aligns with:

    - `"z"` (swivel axis on both shipped profiles): swivel sweeps through
      θ; full arcs always permitted because the swivel axis has
      effectively unbounded range.
    - `"x"` (Prusa tilt axis) or `"y"` (Voron tilt axis): tilt sweeps
      through θ; the requested arc may exceed the profile's tilt range,
      in which case ADR-001's clamping policy applies — refuse loudly by
      default, opt into arc-split via `allow_tilt_arc_split=true` with
      explicit `arc_split_count`.

    See ADR-001 (`docs/adr/0001-wrap-tilt-clamping.md`).

    `conformal_arc_sampling_mm` overrides the default (1 sample per
    `line_width_mm` of arc length). Different bioinks have different
    sensible feature sizes; a 30G needle laying 100 µm collagen wants a
    finer sampling than a 22G needle laying 400 µm GelMA.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["wrap_around_axis"] = "wrap_around_axis"
    wrap_axis: Literal["x", "y", "z"] = "z"
    cylinder_radius_mm: float = Field(gt=0.0, description="Cylinder radius in mm.")
    arc_start_deg: float = Field(default=-180.0, description="Wrap arc start angle (deg).")
    arc_end_deg: float = Field(default=180.0, description="Wrap arc end angle (deg).")
    conformal_arc_sampling_mm: float | None = Field(
        default=None,
        gt=0.0,
        description="Override arc-sample spacing. None → defaults to line_width_mm.",
    )
    allow_tilt_arc_split: bool = Field(
        default=False,
        description=(
            "ADR-001: opt-in to splitting a wrap-tilt arc that exceeds the "
            "profile's tilt range into N sub-arcs with retract-clear moves "
            "between them. Default False = refuse-loudly."
        ),
    )
    arc_split_count: int = Field(
        default=1,
        ge=1,
        description=(
            "ADR-001: when allow_tilt_arc_split=true, the number of equal "
            "sub-arcs to split into. Must be >= the minimum required by the "
            "profile's tilt range; lower values still raise ClampingExceededError."
        ),
    )


SlicingMode = FlatSlicing | WrapAroundAxisSlicing


class SlicingParams(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    layer_height_mm: float = Field(default=0.2, gt=0.0)
    line_width_mm: float = Field(default=0.4, gt=0.0)
    print_speed_mm_per_min: float = Field(default=600.0, gt=0.0)
    travel_speed_mm_per_min: float = Field(default=1200.0, gt=0.0)
    # Deprecated in 2c — kept for back-compat; the bath module now owns this
    # multiplier and is consulted per-travel-Z. See bath/models.py.
    travel_speed_reduction_in_bath: float = Field(default=0.5, gt=0.0, le=1.0)
    # Slicing mode: flat (default) or wrap-around-axis (2c conformal).
    mode: SlicingMode = Field(default_factory=FlatSlicing)
    # Infill — see ADR-002 for default pattern reasoning.
    infill_density: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Infill density in [0, 1]. 0.0 = perimeter only. 0.2 = 20% fill.",
    )
    infill_pattern: Literal["rectilinear"] = Field(
        default="rectilinear",
        description="Infill pattern (v0.1.0 ships rectilinear only — see ADR-002).",
    )
    infill_angle_deg: float = Field(
        default=0.0,
        description="Base angle of rectilinear scan-lines (deg); layer N rotates by 90·N.",
    )


class Recipe(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    syringes: list[Syringe] = Field(min_length=1)
    slicing: SlicingParams = Field(default_factory=lambda: SlicingParams())
    print_orientation: PrintOrientation = Field(default_factory=FixedOrientation)
    # Optional bath spec; None means "no bath modelled" and travels use the
    # legacy uniform `slicing.travel_speed_reduction_in_bath` multiplier.
    bath: BathSpec | None = None
    notes: str = ""

    @model_validator(mode="after")
    def _check_unique_syringe_ids(self) -> Recipe:
        ids = [s.id for s in self.syringes]
        if len(set(ids)) != len(ids):
            raise ValueError(f"syringe ids must be unique, got {ids}")
        return self


__all__ = [
    "Needle",
    "Recipe",
    "Region",
    "RegionAll",
    "RegionBBox",
    "SlicingParams",
    "Syringe",
]
