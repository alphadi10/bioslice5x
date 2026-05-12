"""FRESH support bath model.

The bath has a surface geometry, a rheology (yield-stress / effective
viscosity), and a temperature profile. Path generation queries the bath for
the travel-speed reduction at a given machine-frame Z; the bath model is
the single source of truth.

Phase 2c ships a `plane_at_z` surface model and a single travel-speed
multiplier — enough to validate the API shape that 2d+ will use for a real
bath drag model. Rheology beyond the multiplier is deferred (it needs
empirical calibration per bath formulation that we don't have yet).
"""

from __future__ import annotations

from bioslice5x.bath.loader import load_bath
from bioslice5x.bath.models import BathSpec, PlaneBath

__all__ = ["BathSpec", "PlaneBath", "load_bath"]
