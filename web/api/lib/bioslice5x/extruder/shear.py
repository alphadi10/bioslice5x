"""Wall shear stress computation for syringe-bioprinter pipe flow.

v1 ships the Newtonian wall-shear-stress formula `τ_w = (4·μ·Q)/(π·r³)`
using each bioink's zero-shear (bulk) viscosity as μ.

**Conservative direction (per reviewer guidance):**
For shear-thinning bioinks like collagen and GelMA, the real Rabinowitsch-
corrected wall stress can differ from this estimate by a factor of 2–3 at
typical concentrations. With bulk viscosity as μ, the Newtonian estimate
*over-predicts* wall stress because the real shear-thinned viscosity at the
wall is lower — so a "safe" Newtonian result is more likely safe in reality.
v2 will replace this with Rabinowitsch-Mooney corrections for power-law and
Herschel-Bulkley fits.

The G-code header carries the v1-Newtonian caveat so anyone reading the
output knows the approximation is in play.
"""

from __future__ import annotations

import math

# Avoid division explosion for absurdly thin needles or zero flow.
_EPS = 1e-12


def newtonian_wall_shear_stress_pa(
    flow_rate_uL_per_s: float,
    needle_inner_diameter_mm: float,
    bulk_viscosity_pa_s: float,
) -> float:
    """Compute Newtonian wall shear stress for cylindrical pipe flow.

    All arguments must be positive; returns 0.0 for zero flow (handles
    travel moves cleanly without callers having to branch).
    """
    if flow_rate_uL_per_s <= _EPS:
        return 0.0
    if needle_inner_diameter_mm <= _EPS:
        raise ValueError(f"needle ID must be positive, got {needle_inner_diameter_mm}")
    if bulk_viscosity_pa_s <= _EPS:
        raise ValueError(f"viscosity must be positive, got {bulk_viscosity_pa_s}")

    # Convert µL/s → m³/s: 1 µL = 1e-9 m³
    q_m3_per_s = flow_rate_uL_per_s * 1.0e-9
    # Convert needle ID mm → m, then radius
    r_m = (needle_inner_diameter_mm * 1.0e-3) / 2.0

    # Newtonian Poiseuille wall shear stress: τ = 4·μ·Q / (π·r³)
    return (4.0 * bulk_viscosity_pa_s * q_m3_per_s) / (math.pi * r_m**3)


__all__ = ["newtonian_wall_shear_stress_pa"]
