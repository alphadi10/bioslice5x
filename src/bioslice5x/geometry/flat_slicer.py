"""Flat horizontal slicer — Phase 2a baseline.

Cuts the mesh with z = const planes and returns ordered 2D polygons per
layer. No curved layers, no kinematic transform. Phase 2c replaces this with
the conformal slicer; the data type returned here is the same so downstream
pathing/postprocessor code is unchanged.
"""

from __future__ import annotations

from typing import Any, cast

import numpy as np
import trimesh

from bioslice5x.geometry.mesh import mesh_z_extent
from bioslice5x.geometry.types import LayerGeometry, Polygon2D


def _z_heights(z_min: float, z_max: float, layer_height: float) -> list[float]:
    """Layer z-coordinates from the mesh's z_min + layer_height up to z_max."""
    if layer_height <= 0:
        raise ValueError(f"layer_height must be > 0, got {layer_height}")
    if z_max <= z_min:
        raise ValueError(f"empty z range [{z_min}, {z_max}]")
    first = z_min + layer_height / 2.0
    n = max(1, int(np.floor((z_max - first) / layer_height)) + 1)
    return [first + i * layer_height for i in range(n)]


def flat_slice(mesh: trimesh.Trimesh, layer_height_mm: float) -> list[LayerGeometry]:
    """Slice a mesh into horizontal layers of constant z height.

    Returns one LayerGeometry per layer that produced any geometry; empty
    sections are omitted. Layers are ordered z-ascending.
    """
    z_min, z_max = mesh_z_extent(mesh)
    heights = _z_heights(z_min, z_max, layer_height_mm)

    sections = cast(
        Any,
        mesh.section_multiplane(
            plane_origin=np.array([0.0, 0.0, 0.0]),
            plane_normal=np.array([0.0, 0.0, 1.0]),
            heights=np.array(heights),
        ),
    )

    layers: list[LayerGeometry] = []
    for z, section in zip(heights, sections, strict=True):
        if section is None:
            continue
        polys: list[Polygon2D] = []
        for shapely_poly in section.polygons_full:
            exterior_coords = tuple((float(x), float(y)) for x, y in shapely_poly.exterior.coords)
            # shapely closes the loop with a repeated final vertex; trim it
            if exterior_coords and exterior_coords[0] == exterior_coords[-1]:
                exterior_coords = exterior_coords[:-1]
            if len(exterior_coords) >= 3:
                polys.append(Polygon2D(z=z, points=exterior_coords, is_hole=False))
            for interior in shapely_poly.interiors:
                hole_coords = tuple((float(x), float(y)) for x, y in interior.coords)
                if hole_coords and hole_coords[0] == hole_coords[-1]:
                    hole_coords = hole_coords[:-1]
                if len(hole_coords) >= 3:
                    polys.append(Polygon2D(z=z, points=hole_coords, is_hole=True))
        if polys:
            layers.append(LayerGeometry(z=z, polygons=tuple(polys)))

    return layers


__all__ = ["flat_slice"]
