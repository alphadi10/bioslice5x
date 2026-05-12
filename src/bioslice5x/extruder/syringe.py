"""Displacement-driven syringe model.

Maps volumetric extrusion (µL) onto plunger displacement (mm) via the
syringe's inner-bore cross-section. v1 ships this as the only Extruder
implementation; v2 adds pneumatic via a sibling implementation behind the
same `Extruder` Protocol.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from bioslice5x.bioink.models import Bioink, CellPayload
from bioslice5x.recipe.models import Needle


@dataclass(frozen=True)
class DisplacementSyringe:
    """A stepper-driven syringe with a defined inner bore and nozzle.

    `barrel_inner_diameter_mm` is the syringe BARREL bore (used to convert
    extrusion volume to plunger displacement). `needle.inner_diameter_mm` is
    the NEEDLE bore (used to compute wall shear at the deposition tip).
    """

    syringe_id: int
    barrel_inner_diameter_mm: float
    total_volume_uL: float
    needle: Needle
    bioink: Bioink
    cell_payload: CellPayload
    temperature_setpoint_c: float
    # Volumetric retract emitted around travels and sub-arc boundaries.
    # 0.0 disables retract; otherwise the emitter prepends a `G1 E-<mm>`
    # line before each travel and a `G1 E+<mm>` line after, where mm is
    # `volume_to_plunger_mm(retract_volume_uL)`. See pathing/types.py
    # for the move-level contract and rrf.py for the emission.
    retract_volume_uL: float = 0.0

    def __post_init__(self) -> None:
        if self.barrel_inner_diameter_mm <= 0:
            raise ValueError("barrel_inner_diameter_mm must be > 0")
        if self.total_volume_uL <= 0:
            raise ValueError("total_volume_uL must be > 0")
        if self.retract_volume_uL < 0:
            raise ValueError("retract_volume_uL must be >= 0")
        lo, hi = self.bioink.working_temperature_c
        if not (lo - 1.0 <= self.temperature_setpoint_c <= hi + 1.0):
            raise ValueError(
                f"temperature_setpoint_c {self.temperature_setpoint_c} outside "
                f"bioink working range {(lo, hi)} for {self.bioink.name}"
            )

    @property
    def barrel_cross_section_mm2(self) -> float:
        r_mm = self.barrel_inner_diameter_mm / 2.0
        return math.pi * r_mm * r_mm

    def volume_to_plunger_mm(self, volume_uL: float) -> float:
        """Convert displaced bioink volume (µL) to plunger linear displacement (mm).

        1 µL = 1 mm³, so plunger mm = volume_mm3 / barrel_cross_section_mm2.
        """
        return volume_uL / self.barrel_cross_section_mm2

    def barrel_to_needle_contraction_ratio(self) -> float:
        """Ratio of barrel cross-section area to needle cross-section area.

        Reviewer threshold (BIOPRINTING_REQUIREMENTS.md §4): warn above 100:1.
        v1 surfaces this as a metric in the cell-stress report; v1 does not
        gate on it.
        """
        needle_r_mm = self.needle.inner_diameter_mm / 2.0
        needle_area = math.pi * needle_r_mm * needle_r_mm
        return self.barrel_cross_section_mm2 / needle_area


__all__ = ["DisplacementSyringe"]
