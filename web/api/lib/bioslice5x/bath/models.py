"""Bath geometry, provenance, and travel-speed lookup.

`BathSpec` is the recipe-level handle on the bath; `PlaneBath` is the
single concrete surface model in v1.1 (horizontal plane at a chosen Z,
with the print sitting above it). Future kinds (`dish`, `custom`) plug in
as sibling pydantic models under the same `BathSpec` discriminated union.

API shape:
- `travel_speed_multiplier(point: Point3D) → float` — accepts a 3-point so
  forward-compatible bath kinds that depend on XY (meniscus, dish, partial
  fills) can use the same surface without a callers-update churn. `PlaneBath`
  ignores XY by definition. Path-segment-aware queries (averaging the
  multiplier along a move) are a v2 extension via a new method, not a
  signature change.

Provenance:
- `calibrated_against` mirrors the bioink/cell convention. Bath drag is
  empirical; shipping a value without naming its origin is the same
  reproducibility trap as shipping an uncalibrated cell-shear threshold.
"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


@runtime_checkable
class Point3DLike(Protocol):
    """Structural typing for machine-frame points.

    The bath module does not import `bioslice5x.pathing.types.Point3D`
    directly to avoid a recipe-models ↔ pathing ↔ bath circular import.
    Anything with x, y, z attributes works (in practice, only `Point3D`
    is ever passed in).
    """

    @property
    def x(self) -> float: ...
    @property
    def y(self) -> float: ...
    @property
    def z(self) -> float: ...


@runtime_checkable
class BathSurface(Protocol):
    """Bath model interface — every concrete bath kind implements this."""

    kind: str
    calibrated_against: str

    def travel_speed_multiplier(self, point: Point3DLike) -> float:
        """Speed multiplier `m ∈ (0, 1]` at the given machine-frame point."""
        ...


class PlaneBath(BaseModel):
    """Horizontal-plane support bath: a flat gelatin pool at `surface_z_mm`.

    Travels with `point.z < surface_z_mm` are below the surface (in bath)
    and get the configured speed reduction. Travels above run at full speed.
    XY position is ignored — real meniscus / dish effects need a different
    bath kind.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["plane"] = "plane"
    surface_z_mm: float = 0.0
    travel_speed_multiplier_in_bath: float = Field(default=0.5, gt=0.0, le=1.0)
    calibrated_against: str = "uncalibrated, literature default"

    def travel_speed_multiplier(self, point: Point3DLike) -> float:
        return self.travel_speed_multiplier_in_bath if point.z < self.surface_z_mm else 1.0


# Discriminated union for future surface kinds. v1.1 has only "plane".
BathSpec = PlaneBath


__all__ = ["BathSpec", "BathSurface", "PlaneBath", "Point3DLike"]
