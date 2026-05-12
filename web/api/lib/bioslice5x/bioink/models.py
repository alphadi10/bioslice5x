"""Pydantic models for bioinks and cell payloads.

Strict schemas — `extra="forbid"` so typos in user-authored YAML files surface
at load time rather than producing silent defaults. Every model carries a
`calibrated_against` field whose default is the literal string
"uncalibrated, literature default" — this surfaces the placeholder status of
shipped reference values in downstream cell-stress reports and G-code headers.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RheologicalModel(BaseModel):
    """Rheology for a bioink. Field requirements depend on `kind`.

    v1 uses Newtonian wall-shear-stress (`τ_w = 4·μ·Q/(π·r³)`) for all kinds
    as a conservative-ish approximation when µ is the bulk/zero-shear viscosity.
    v2 will apply Rabinowitsch-Mooney corrections for the non-Newtonian fits.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["newtonian", "power_law", "herschel_bulkley"]
    viscosity_pa_s: float | None = Field(default=None, description="Newtonian / bulk viscosity.")
    consistency_k: float | None = Field(default=None, description="K in K·γ^n for power-law / HB.")
    flow_index_n: float | None = Field(default=None, description="n in K·γ^n.")
    yield_stress_pa: float | None = Field(default=None, description="τ₀ for Herschel-Bulkley.")

    @model_validator(mode="after")
    def _check_fields_for_kind(self) -> RheologicalModel:
        if self.kind == "newtonian" and self.viscosity_pa_s is None:
            raise ValueError("newtonian rheology requires viscosity_pa_s")
        if self.kind in ("power_law", "herschel_bulkley") and (
            self.consistency_k is None or self.flow_index_n is None
        ):
            raise ValueError(f"{self.kind} requires consistency_k and flow_index_n")
        if self.kind == "herschel_bulkley" and self.yield_stress_pa is None:
            raise ValueError("herschel_bulkley requires yield_stress_pa")
        return self

    def bulk_viscosity_pa_s(self) -> float:
        """Conservative viscosity for the v1 Newtonian shear-stress estimate."""
        if self.viscosity_pa_s is not None:
            return self.viscosity_pa_s
        # For power-law/HB without an explicit bulk viscosity, use K as a
        # zero-shear-rate-ish proxy. Documented in the module docstring.
        if self.consistency_k is not None:
            return self.consistency_k
        raise ValueError("rheology has no usable viscosity for shear estimation")


class CellPayload(BaseModel):
    """A cell type loaded into a syringe, with its safety threshold.

    `max_wall_shear_stress_pa` is the threshold above which the slicer raises
    `CellViabilityError`. Shipped defaults are literature-derived placeholders;
    operators should override per-lab-validated values.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    cell_type: str
    cell_density_per_mL: float = Field(gt=0.0)
    max_wall_shear_stress_pa: float = Field(gt=0.0)
    calibrated_against: str = "uncalibrated, literature default"
    notes: str = ""


class Bioink(BaseModel):
    """A bioink material with rheology, working envelope, and provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    density_g_per_mL: float = Field(gt=0.0)
    rheology: RheologicalModel
    working_temperature_c: tuple[float, float]
    crosslinking: Literal["thermal", "ionic", "photo", "enzymatic", "none"]
    calibrated_against: str = "uncalibrated, literature default"
    notes: str = ""

    @model_validator(mode="after")
    def _check_temp_window(self) -> Bioink:
        lo, hi = self.working_temperature_c
        if lo > hi:
            raise ValueError(f"working_temperature_c low ({lo}) must be <= high ({hi})")
        return self


__all__ = ["Bioink", "CellPayload", "RheologicalModel"]
