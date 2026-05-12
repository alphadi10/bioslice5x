"""Mesh I/O, slicing primitives, layer geometry types.

Phase 2a ships flat horizontal slicing only. Phase 2c replaces flat_slice
with a conformal slicer that returns the same LayerGeometry type.
"""

from __future__ import annotations

from bioslice5x.geometry.flat_slicer import flat_slice
from bioslice5x.geometry.mesh import load_mesh, mesh_z_extent
from bioslice5x.geometry.types import LayerGeometry, Polygon2D

__all__ = ["LayerGeometry", "Polygon2D", "flat_slice", "load_mesh", "mesh_z_extent"]
