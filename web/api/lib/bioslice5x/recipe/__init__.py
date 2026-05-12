"""Recipe schema and loader.

A Recipe is the user-authored input describing what to print: which syringes
carry which bioinks, which mesh regions each owns, and slicing parameters.
The schema treats single-bioink-whole-mesh as the N=1 trivial case of the
general multi-region form (see ARCHITECTURE.md §8.5).
"""

from __future__ import annotations

from bioslice5x.recipe.loader import load_recipe
from bioslice5x.recipe.models import (
    FixedOrientation,
    Needle,
    PerLayerOrientation,
    PrintOrientation,
    Recipe,
    Region,
    SlicingParams,
    Syringe,
)

__all__ = [
    "FixedOrientation",
    "Needle",
    "PerLayerOrientation",
    "PrintOrientation",
    "Recipe",
    "Region",
    "SlicingParams",
    "Syringe",
    "load_recipe",
]
