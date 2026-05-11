"""Deprecated module name — use `bioslice5x.bioink.loader` instead.

This stub exists only to make the name-collision with the YAML data directory
explicit. The real implementation is in `loader.py`.
"""

from __future__ import annotations

from bioslice5x.bioink.loader import (
    load_bioink_by_name,
    load_bioink_yaml,
    load_cell_by_name,
    load_cells_yaml,
    load_default_library,
)

__all__ = [
    "load_bioink_by_name",
    "load_bioink_yaml",
    "load_cell_by_name",
    "load_cells_yaml",
    "load_default_library",
]
