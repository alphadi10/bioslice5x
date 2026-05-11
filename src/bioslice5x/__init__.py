"""BioSlice5X — open-source 5-axis slicer for syringe-based bioprinting.

Library-first surface: every CLI verb is a thin shim over these public
functions and classes. See ARCHITECTURE.md §8.2.
"""

from __future__ import annotations

from bioslice5x.bioink.loader import load_bioink_by_name, load_cell_by_name, load_default_library
from bioslice5x.errors import (
    BathCollisionError,
    BioSlice5XError,
    CellViabilityError,
    ClampingExceededError,
    KinematicSingularityError,
    ProfileValidationError,
)
from bioslice5x.geometry.mesh import load_mesh
from bioslice5x.profile.loader import load_profile
from bioslice5x.recipe.loader import load_recipe
from bioslice5x.slicer import Slicer, SliceResult

__version__: str = "0.1.0"

__all__ = [
    "BathCollisionError",
    "BioSlice5XError",
    "CellViabilityError",
    "ClampingExceededError",
    "KinematicSingularityError",
    "ProfileValidationError",
    "SliceResult",
    "Slicer",
    "__version__",
    "load_bioink_by_name",
    "load_cell_by_name",
    "load_default_library",
    "load_mesh",
    "load_profile",
    "load_recipe",
]
