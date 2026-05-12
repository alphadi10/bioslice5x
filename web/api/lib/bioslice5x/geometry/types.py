"""Geometry data types.

These are deliberately lightweight so they round-trip cleanly through the
pipeline without trimesh/shapely leakage. Real implementations of slicing
and pathing produce these types; downstream stages don't need to know which
backend produced them.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Polygon2D:
    """A closed 2D polygon at a fixed z height.

    `points` is a list of (x, y) tuples. The polygon is implicitly closed —
    the first and last point are not duplicated.
    """

    z: float
    points: tuple[tuple[float, float], ...]
    is_hole: bool = False  # True if this is an interior hole, not an exterior boundary

    def __post_init__(self) -> None:
        if len(self.points) < 3:
            raise ValueError(f"Polygon2D needs >=3 points, got {len(self.points)}")


@dataclass(frozen=True)
class LayerGeometry:
    """All polygons at a single z height.

    A layer may have multiple exterior boundaries (e.g., when a mesh splits
    into disconnected regions at a given height) and/or holes inside them.
    """

    z: float
    polygons: tuple[Polygon2D, ...]


__all__ = ["LayerGeometry", "Polygon2D"]
