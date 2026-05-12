"""Per-region geometry clipping.

Filters slicer-produced `LayerGeometry` sequences against per-syringe
spatial regions. v0.1.1 supports `RegionAll` (no-op) and `RegionBBox`
(3D AABB intersection). Future kinds (`submesh`, `volume_fraction`)
become siblings of `_clip_by_bbox` here.

Implementation: layers outside the bbox's z-range are dropped whole;
remaining layers' shapely polygons are intersected with the XY rectangle.
Exterior + hole topology is preserved.
"""

from __future__ import annotations

from collections.abc import Sequence

from shapely.geometry import MultiPolygon, Polygon, box
from shapely.geometry.base import BaseGeometry

from bioslice5x.geometry.types import LayerGeometry, Polygon2D
from bioslice5x.recipe.models import Region, RegionAll, RegionBBox


def _shapely_layer(polygons: tuple[Polygon2D, ...]) -> BaseGeometry | None:
    """Build a shapely (Multi)Polygon from a layer's exterior+hole list.

    Each exterior owns the holes that lie strictly inside it. This mirrors
    `pathing.infill._shapely_polygon_with_holes` but is duplicated here
    rather than imported to keep the geometry layer free of pathing imports
    (per the import-linter contracts; see `pyproject.toml` §lint).
    """
    if not polygons:
        return None
    exteriors = [p for p in polygons if not p.is_hole]
    holes = [p for p in polygons if p.is_hole]
    if not exteriors:
        return None
    polys: list[Polygon] = []
    for ext in exteriors:
        ext_poly = Polygon(list(ext.points))
        ext_holes = [list(h.points) for h in holes if Polygon(h.points).within(ext_poly)]
        polys.append(Polygon(list(ext.points), holes=ext_holes))
    if len(polys) == 1:
        return polys[0]
    return MultiPolygon(polys)


def _polygons_from_shapely(geom: BaseGeometry, z: float) -> tuple[Polygon2D, ...]:
    """Convert a shapely (Multi)Polygon back to a Polygon2D tuple.

    Empty geometry returns an empty tuple. Each Polygon's exterior is
    appended as `is_hole=False`; each interior ring as `is_hole=True`.
    GeometryCollections (which shapely returns from some intersections)
    are flattened by extracting any Polygon components and discarding
    everything else (lines, points — degenerate boundary cases).
    """
    if geom.is_empty:
        return ()
    polys_list: list[Polygon] = []
    if isinstance(geom, Polygon):
        polys_list = [geom]
    elif isinstance(geom, MultiPolygon):
        polys_list = list(geom.geoms)
    elif hasattr(geom, "geoms"):
        # GeometryCollection — keep only the Polygon components.
        polys_list = [g for g in geom.geoms if isinstance(g, Polygon)]
    out: list[Polygon2D] = []
    for p in polys_list:
        ext_coords = list(p.exterior.coords)
        # Shapely closes rings (first point repeated at end); Polygon2D's
        # contract is "implicitly closed, first/last not duplicated."
        if len(ext_coords) >= 2 and ext_coords[0] == ext_coords[-1]:
            ext_coords = ext_coords[:-1]
        if len(ext_coords) < 3:
            continue
        out.append(Polygon2D(z=z, points=tuple((float(x), float(y)) for x, y in ext_coords)))
        for interior in p.interiors:
            int_coords = list(interior.coords)
            if len(int_coords) >= 2 and int_coords[0] == int_coords[-1]:
                int_coords = int_coords[:-1]
            if len(int_coords) < 3:
                continue
            out.append(
                Polygon2D(
                    z=z,
                    points=tuple((float(x), float(y)) for x, y in int_coords),
                    is_hole=True,
                )
            )
    return tuple(out)


def _clip_layer_by_bbox(layer: LayerGeometry, region: RegionBBox) -> LayerGeometry | None:
    """Clip a single layer's polygons by the bbox.

    Returns None when the layer's z is outside the bbox's z-range or
    when the intersection is empty.
    """
    if not (region.min[2] <= layer.z <= region.max[2]):
        return None
    shape = _shapely_layer(layer.polygons)
    if shape is None or shape.is_empty:
        return None
    rect = box(region.min[0], region.min[1], region.max[0], region.max[1])
    clipped = shape.intersection(rect)
    if clipped.is_empty:
        return None
    polys = _polygons_from_shapely(clipped, layer.z)
    if not polys:
        return None
    return LayerGeometry(z=layer.z, polygons=polys)


def clip_layers_by_region(layers: Sequence[LayerGeometry], region: Region) -> list[LayerGeometry]:
    """Filter / clip a layer sequence per a syringe's region.

    `RegionAll` returns the layers unchanged. `RegionBBox` drops layers
    outside the z-range and clips remaining layers' polygons against
    the XY rectangle. Future region kinds dispatch here.

    Empty layers (no polygons after clipping) are dropped from the
    result — downstream pathing can't do anything useful with them and
    the slicer's per-syringe move list stays clean.
    """
    if isinstance(region, RegionAll):
        return list(layers)
    if isinstance(region, RegionBBox):
        out: list[LayerGeometry] = []
        for layer in layers:
            clipped = _clip_layer_by_bbox(layer, region)
            if clipped is not None:
                out.append(clipped)
        return out
    raise NotImplementedError(f"unsupported region kind: {type(region).__name__}")


__all__ = ["clip_layers_by_region"]
