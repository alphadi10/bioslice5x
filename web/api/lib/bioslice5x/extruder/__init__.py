"""Displacement-driven syringe model, shear-stress math, validation pass.

v1 ships displacement-based extrusion only; v2 adds pneumatic behind the
same shape. See ARCHITECTURE.md §4.1.
"""

from __future__ import annotations

from bioslice5x.extruder.shear import newtonian_wall_shear_stress_pa
from bioslice5x.extruder.syringe import DisplacementSyringe
from bioslice5x.extruder.validate import SegmentStress, StressReport, validate_path

__all__ = [
    "DisplacementSyringe",
    "SegmentStress",
    "StressReport",
    "newtonian_wall_shear_stress_pa",
    "validate_path",
]
